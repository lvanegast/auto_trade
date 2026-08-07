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
    
    def __init__(self, db, worker_id: str):
        self.db = db
        self.worker_id = worker_id
        # Track already-resolved market slugs to prevent duplicate alerts
        self._already_resolved: set = set()
    
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
                unresolved_opps = self.db.get_pending_opportunities() or []
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

        for opp in unresolved_opps:
            event_id = opp.get("event_id", "") if isinstance(opp, dict) else (opp[1] if len(opp) > 1 else "")
            market_slug = self._extract_market_slug(event_id)
            if market_slug and market_slug not in market_groups:
                market_groups[market_slug] = []

        for market_slug, positions in market_groups.items():
            try:
                resolved = await self._check_market_resolution(market_slug, positions)
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
        prefixes = ["limitless_sport_", "polymarket_", "limitless_crypto_", "limitless_"]
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
        self, market_slug: str, positions: List[Dict]
    ) -> Optional[ResolvedMarket]:
        """
        Verifica si un mercado resolvió consultando la API de Limitless.
        """
        if market_slug in self._already_resolved:
            return None

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
                    return None
                
                status = getattr(market, "status", None)
                winning_index = getattr(market, "winning_outcome_index", None)
                condition_id = getattr(market, "condition_id", None)
                
                # Verificar si el mercado resolvió
                if status != "RESOLVED":
                    return None
                
                # Determinar outcome ganador
                if winning_index is not None:
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
                # Mark as resolved to prevent duplicate alerts
                self._already_resolved.add(market_slug)
                try:
                    if hasattr(self.db, "update_opportunity_resolution"):
                        self.db.update_opportunity_resolution(market_slug, f"resolved_{winning_outcome}")
                except Exception:
                    pass

                try:
                    from src.telegram_bot import telegram_bot
                    if telegram_bot.enabled:
                        telegram_bot.send_alert(
                            "profit" if winning_outcome in ("YES", "NO") else "info",
                            f"<b>Evento Resuelto</b>\n<b>Mercado:</b> {market_slug}\n<b>Resultado Ganador:</b> {winning_outcome}",
                            event_id=market_slug
                        )
                except Exception:
                    pass
                
                return resolved
                
            except Exception as e:
                # Mercado puede no existir o error de red
                return None


# Singleton
_resolution_monitor: Optional[ResolutionMonitor] = None


def get_resolution_monitor(db=None, worker_id: str = None) -> ResolutionMonitor:
    """Obtiene o crea la instancia global de ResolutionMonitor."""
    global _resolution_monitor
    if _resolution_monitor is None and db is not None:
        _resolution_monitor = ResolutionMonitor(db, worker_id)
    return _resolution_monitor
