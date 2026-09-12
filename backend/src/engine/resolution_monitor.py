"""
ResolutionMonitor — detecta cuando mercados resuelven y determina ganador.

Flujo:
1. Polling de status de mercados con posiciones abiertas
2. Cuando status == RESOLVED → determinar ganador
3. Notificar a RedeemExecutor para cobrar
"""

import asyncio
import os
import time
from typing import Optional, Dict, List, Any
from dataclasses import dataclass


@dataclass
class ResolvedMarket:
    """Resultado de un mercado resuelto."""
    market_slug: str
    condition_id: str
    status: str
    winning_outcome_index: Optional[int]  # 0=YES, 1=NO, None=split
    winning_outcome: str  # "YES", "NO", "SPLIT"
    payout_numerators: Optional[List[int]]  # [50, 50] for split
    resolved_at: Optional[str]


class ResolutionMonitor:
    """
    Monitorea posiciones abiertas y detecta cuando los mercados resuelven.
    
    Uso:
        monitor = ResolutionMonitor(db, worker_id)
        resolved = await monitor.check_open_positions()
        for market in resolved:
            # Process resolved market
    """

    # Class-level set: persiste entre instancias (se crea una instancia por ciclo
    # de sync), evita alertas duplicadas por worker y entre workers.
    # No se descartan slugs: el cap es tan alto que en la práctica es permanente,
    # para que un mercado ya resuelto NUNCA vuelva a generar una alerta.
    _already_resolved: set = set()

    def __init__(self, db, worker_id: str):
        self.db = db
        self.worker_id = worker_id

    @classmethod
    def _mark_resolved(cls, market_slug: str):
        """Marca un market como resuelto. El set persiste para el proceso."""
        cls._already_resolved.add(market_slug)
        # Límite defensivo de memoria: 50k slugs (~MBs), muy por encima del
        # volumen real diario. Antes este cap (1000→500) hacía que slugs viejos
        # fueran re-detectados → mensajes de resolución duplicados.
        if len(cls._already_resolved) > 50000:
            cls._already_resolved = set(list(cls._already_resolved)[-40000:])

    async def check_open_positions_and_opportunities(self) -> List[ResolvedMarket]:
        """
        Verifica tanto posiciones abiertas como oportunidades registradas sin resolver.
        """
        resolved_markets = []
        
        # 1. Obtener posiciones abiertas
        open_positions = self.db.get_open_positions(worker_id=self.worker_id) or []
        
        # 2. Obtener oportunidades registradas sin resolver
        unresolved_opps = []
        try:
            if hasattr(self.db, "get_pending_opportunities"):
                # Scoped a ESTE worker — sin este filtro, todos los workers ven
                # las mismas oportunidades pendientes y cada uno intenta resolverlas
                # y alertar por su cuenta (mensajes de Telegram duplicados).
                unresolved_opps = self.db.get_pending_opportunities(worker_id=self.worker_id) or []
        except Exception as e:
            print(f"[ResolutionMonitor Error] {e}")

        if not open_positions and not unresolved_opps:
            return resolved_markets

        market_groups = {}
        for pos in open_positions:
            symbol = pos.get("symbol", "") if isinstance(pos, dict) else (pos[2] if len(pos) > 2 else "")
            market_slug = self._extract_market_slug(symbol)
            if market_slug:
                if market_slug not in market_groups:
                    market_groups[market_slug] = []
                market_groups[market_slug].append(pos)

        opp_map = {}
        for opp in unresolved_opps:
            event_id = opp.get("event_id", "") if isinstance(opp, dict) else (opp[1] if len(opp) > 1 else "")
            # Si la oportunidad guardó su market_slug real (ej. group_slug de
            # Limitless para sports), úsalo directamente. El event_id canónico
            # (match_*) NO es un slug consultable en la API.
            market_slug = None
            if isinstance(opp, dict) and opp.get("market_slug"):
                market_slug = opp.get("market_slug")
            if not market_slug:
                market_slug = self._extract_market_slug(event_id)
            if market_slug:
                opp_map[market_slug] = opp
                if market_slug not in market_groups:
                    market_groups[market_slug] = []

        for market_slug, positions in market_groups.items():
            try:
                opp_data = opp_map.get(market_slug, {})
                resolved = await self._check_market_resolution(market_slug, positions, opp_data=opp_data)
                if resolved:
                    resolved_markets.append(resolved)
            except Exception as e:
                self.db.log(
                    "WARNING",
                    f"[ResolutionMonitor] Error verificando {market_slug}: {e}",
                    self.worker_id,
                )

        return resolved_markets

    async def check_open_positions(self) -> List[ResolvedMarket]:
        return await self.check_open_positions_and_opportunities()
    
    def _extract_market_slug(self, symbol: str) -> Optional[str]:
        """
        Extrae el market_slug del symbol.
        
        Formatos soportados:
        - limitless_sport_{slug}_{outcome}
        - polymarket_{event_id}_{slug}
        - {slug}
        """
        if not symbol:
            return None
        
        # Remover prefijos de plataforma
        prefixes = ["limitless_sniper_", "limitless_sport_", "polymarket_", "limitless_crypto_", "limitless_"]
        slug = symbol
        for prefix in prefixes:
            if slug.startswith(prefix):
                slug = slug[len(prefix):]
                break
        
        # Remover sufijo de outcome (_YES, _NO, _outcome_slug)
        parts = slug.rsplit("_", 1)
        if len(parts) > 1:
            last = parts[-1].upper()
            if last in ("YES", "NO") or last.startswith("0X"):
                slug = parts[0]
        
        return slug if slug else None
    
    async def _check_market_resolution(
        self, market_slug: str, positions: List[Dict], opp_data: Dict = None
    ) -> Optional[ResolvedMarket]:
        """
        Verifica si un mercado resolvió consultando la API de Limitless.
        """
        if market_slug in self._already_resolved:
            return None

        # Reservar el slug ANTES de la llamada de red (que hace `await` y cede
        # el control del event loop). Si no reservamos aquí, dos workers pueden
        # pasar el check de arriba casi al mismo tiempo — mientras el primero
        # todavía espera la respuesta de la API — y ambos terminan alertando
        # por Telegram el mismo evento. Si resulta que NO estaba resuelto, se
        # libera más abajo para poder re-chequear en el siguiente ciclo.
        self._mark_resolved(market_slug)

        from limitless_sdk.api import HttpClient
        from limitless_sdk.markets import MarketFetcher
        from limitless_sdk.types.api_tokens import HMACCredentials
        
        api_key = os.getenv("LIMITLESS_API_KEY")
        api_secret = os.getenv("LIMITLESS_API_SECRET")
        
        async with HttpClient() as http:
            if api_key and api_secret:
                http.set_hmac_credentials(HMACCredentials(token_id=api_key, secret=api_secret))
            fetcher = MarketFetcher(http)
            
            try:
                # Medir latencia real de la llamada API
                from src.engine.latency_tracker import latency_tracker
                
                async with latency_tracker.measure("limitless", "get_market") as m:
                    market = await fetcher.get_market(market_slug)
                    m.result = market
                
                if not market:
                    self._already_resolved.discard(market_slug)
                    return None

                status = getattr(market, "status", None)
                winning_index = getattr(market, "winning_outcome_index", None)
                condition_id = getattr(market, "condition_id", None)

                # Verificar si el mercado resolvió
                if status != "RESOLVED":
                    # Para grupos 1xN (N>2), el status del grupo puede permanecer
                    # "FUNDED" mientras los sub-mercados ya resuelven. Verificar
                    # los children como fallback.
                    subs = getattr(market, "markets", None) or []
                    if market.market_type == "group" and subs:
                        resolved_subs = [s for s in subs if getattr(s, "winning_outcome_index", None) is not None]
                        if not resolved_subs:
                            self._already_resolved.discard(market_slug)
                            return None
                        resolved_sub = resolved_subs[0]
                        winning_index = resolved_sub.winning_outcome_index
                        status = "RESOLVED"
                    else:
                        self._already_resolved.discard(market_slug)
                        return None
                
                # Determinar outcome ganador
                winning_sub_slug = None
                if winning_index is not None:
                    if market.market_type == "group":
                        # Un grupo 1xN: el outcome ganador es el sub-market cuyo
                        # YES resolvió a $1.00 (winning_outcome_index == 0).
                        subs = getattr(market, "markets", None) or []
                        winning_subs = [s for s in subs if s.winning_outcome_index == 0]
                        if winning_subs:
                            winning_outcome = winning_subs[0].title or "OUTCOME"
                            winning_sub_slug = getattr(winning_subs[0], "slug", None)
                        elif 0 <= winning_index < len(subs):
                            winning_outcome = subs[winning_index].title or f"OUTCOME_{winning_index}"
                            winning_sub_slug = getattr(subs[winning_index], "slug", None)
                        else:
                            winning_outcome = f"OUTCOME_{winning_index}"
                    else:
                        winning_outcome = "YES" if winning_index == 0 else "NO"
                else:
                    # Split resolution
                    winning_outcome = "SPLIT"
                
                resolved = ResolvedMarket(
                    market_slug=market_slug,
                    condition_id=condition_id or "",
                    status=status,
                    winning_outcome_index=winning_index,
                    winning_outcome=winning_outcome,
                    payout_numerators=None,  # TODO: parse from market
                    resolved_at=None,
                )
                
                self.db.log(
                    "INFO",
                    f"[ResolutionMonitor] Mercado resuelto: {market_slug} → {winning_outcome}",
                    self.worker_id,
                )
                # Mark as resolved to prevent duplicate alerts (class-level, capped)
                self._mark_resolved(market_slug)
                db_event_id = (
                    opp_data.get("event_id", market_slug)
                    if isinstance(opp_data, dict)
                    else (opp_data[1] if isinstance(opp_data, (tuple, list)) and len(opp_data) > 1 else market_slug)
                )
                try:
                    if hasattr(self.db, "update_opportunity_resolution"):
                        self.db.update_opportunity_resolution(db_event_id, f"resolved_{winning_outcome}")
                except Exception:
                    pass

                # Redimir on-chain la(s) pata(s) ganadora(s) que tengan condition_id
                # guardado (posiciones reales, no de observación). De N patas de una
                # canasta 1xN, solo la ganadora vale algo — las demás resuelven a $0
                # y no requieren redeem.
                if winning_outcome != "SPLIT":
                    is_negrisk = market.market_type == "group"
                    allowed_env = os.getenv("ALLOWED_REAL_WORKERS", "").strip()
                    allowed_db = self.db.get_state("ALLOWED_REAL_WORKERS", "") if (self.db and hasattr(self.db, "get_state")) else ""
                    allowed_real_workers = [
                        w.strip() for w in f"{allowed_env},{allowed_db}".split(",") if w.strip()
                    ]
                    for pos in positions:
                        if not isinstance(pos, dict):
                            continue
                        pos_condition_id = pos.get("condition_id")
                        if not pos_condition_id or pos.get("redeemed"):
                            continue
                        if pos.get("worker_id") not in allowed_real_workers:
                            continue

                        pos_symbol = pos.get("symbol", "")
                        leg_token = "NO" if pos_symbol.upper().endswith("_NO") else "YES"
                        if is_negrisk:
                            leg_slug = self._extract_market_slug(pos_symbol)
                            won_this_leg = bool(winning_sub_slug) and leg_slug == winning_sub_slug
                        else:
                            won_this_leg = leg_token == winning_outcome

                        if not won_this_leg:
                            continue

                        try:
                            from src.engine.redeem_executor import get_redeem_executor
                            redeem_executor = get_redeem_executor(self.db, self.worker_id)
                            redeem_result = await redeem_executor.redeem(
                                condition_id=pos_condition_id,
                                winning_outcome="YES",
                                shares=float(pos.get("amount", 0) or 0),
                                is_negrisk=is_negrisk,
                            )
                            if redeem_result.success:
                                self.db.mark_position_redeemed(pos["id"])
                                self.db.log(
                                    "INFO",
                                    f"[Redeem] Pata ganadora {pos_symbol} redimida on-chain: tx={redeem_result.tx_hash}",
                                    self.worker_id,
                                )
                                try:
                                    from src.telegram_bot import telegram_bot
                                    if telegram_bot.enabled:
                                        _shares = float(pos.get("amount", 0) or 0)
                                        _entry = float(pos.get("entry_price", 0) or 0)
                                        _cost = _shares * _entry
                                        _payout = _shares * 1.0
                                        _profit = _payout - _cost
                                        _cat = "crypto" if ("up-or-down" in market_slug or "crypto" in market_slug.lower()) else "sports"
                                        telegram_bot.send_payout_received(
                                            worker_id=self.worker_id,
                                            market_slug=market_slug,
                                            token=leg_token,
                                            amount_won=_shares,
                                            payout_usd=_payout,
                                            cost_usd=_cost,
                                            net_profit_usd=_profit,
                                            tx_hash=redeem_result.tx_hash,
                                            category=_cat,
                                        )
                                except Exception as _e_payout:
                                    print(f"[ResolutionMonitor TG Payout Error] {_e_payout}")
                            else:
                                self.db.log(
                                    "CRITICAL",
                                    f"[Redeem] Falló el redeem de {pos_symbol}: {redeem_result.error}. "
                                    "Requiere reclamo manual.",
                                    self.worker_id,
                                )
                        except Exception as e_redeem:
                            self.db.log(
                                "CRITICAL",
                                f"[Redeem] Error inesperado redimiendo {pos_symbol}: {e_redeem}. "
                                "Requiere reclamo manual.",
                                self.worker_id,
                            )

                try:
                    from src.telegram_bot import telegram_bot
                    if telegram_bot.enabled:
                        entry_price = float(opp_data.get("entry_price", 0.95) if isinstance(opp_data, dict) else (opp_data[4] if isinstance(opp_data, (tuple, list)) and len(opp_data) > 4 else 0.95))
                        expected_profit = 1.0 - entry_price if entry_price < 1.0 else 0.05
                        event_title = opp_data.get("event_title", market_slug) if isinstance(opp_data, dict) else (opp_data[2] if isinstance(opp_data, (tuple, list)) and len(opp_data) > 2 else market_slug)
                        # Determinar sala (sports vs crypto) por el event_id
                        category = "crypto" if ("up-or-down" in market_slug or market_slug.startswith("limitless_sniper_") or "crypto" in market_slug.lower()) else "sports"

                        # Determinar si NUESTRA pata ganó o perdió (posición real o YES del sniper)
                        position_won = None
                        position_pnl = None
                        if positions:
                            pnl = 0.0
                            any_known = False
                            for p in positions:
                                if not isinstance(p, dict):
                                    continue
                                symbol = p.get("symbol", "")
                                amount = float(p.get("amount", 0) or 0)
                                pos_entry = float(p.get("entry_price", 0) or 0)
                                is_no = symbol.upper().endswith("_NO")
                                pos_outcome = "NO" if is_no else "YES"
                                won = pos_outcome == winning_outcome
                                any_known = True
                                pnl += amount * (1.0 - pos_entry) if won else -amount * pos_entry
                            if any_known:
                                position_won = pnl > 0
                                position_pnl = pnl
                        else:
                            # Oportunidad de observación: el PnL paper depende de
                            # la dirección (sniper YES vs 1xN garantizado).
                            direction = opp_data.get("direction", "") if isinstance(opp_data, dict) else ""
                            outcome_count = int(opp_data.get("outcomes_count", 0) or 0) if isinstance(opp_data, dict) else 0
                            if direction in ("BUY_ALL_YES", "BUY_ALL_YES_1XN"):
                                payout = 1.0
                            elif direction in ("BUY_ALL_NO", "BUY_ALL_NO_1XN") and outcome_count > 0:
                                payout = outcome_count - 1
                            else:
                                payout = None
                            if payout is not None:
                                # 1xN garantizado: gana el arbitraje cuando el
                                # mercado resuelve (payout > entry garantizado).
                                position_pnl = payout - entry_price
                                position_won = position_pnl > 0
                            else:
                                # Sniper: compra el lado casi-seguro (YES o NO)
                                if direction == "SNIPER_NO":
                                    position_won = (winning_outcome == "NO")
                                else:
                                    # SNIPER_YES (default): compra YES ~0.97-0.98
                                    position_won = (winning_outcome == "YES")
                                position_pnl = (1.0 - entry_price) if position_won else -entry_price

                        telegram_bot.send_opportunity_resolution(
                            event_id=db_event_id,
                            event_title=event_title,
                            winning_outcome=winning_outcome,
                            entry_price=entry_price,
                            expected_profit=expected_profit,
                            position_won=position_won,
                            position_pnl=position_pnl,
                            category=category,
                        )
                except Exception as e_tg:
                    print(f"[ResolutionMonitor TG Error] {e_tg}")
                
                return resolved
                
            except Exception as e:
                # Mercado puede no existir o error de red — liberar la reserva
                # para poder reintentar en el próximo ciclo.
                self._already_resolved.discard(market_slug)
                return None


# Singleton
_resolution_monitor: Optional[ResolutionMonitor] = None


def get_resolution_monitor(db=None, worker_id: str = None) -> ResolutionMonitor:
    """Obtiene o crea la instancia global de ResolutionMonitor."""
    global _resolution_monitor
    if _resolution_monitor is None and db is not None:
        _resolution_monitor = ResolutionMonitor(db, worker_id)
    return _resolution_monitor
