"""
Telegram Bot for AutoTrade — Alerts and Commands

Sends real-time alerts and responds to user commands.
Works on both local and Railway deployments.

DEDUP: Once an alert is sent for an event_id, no more alerts until resolution.
COMMANDS: /status, /positions, /pnl, /workers
"""

import os
import json
import asyncio
import time
import threading
import urllib.request
from datetime import datetime
from src.utils.bounded_dict import BoundedTimeDict


class TelegramBot:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.enabled = bool(self.token and self.chat_id)
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        # Sub-salones: chats dedicados por categoría. Si no están configurados,
        # todo cae al chat_id principal. Alternativa con topics: si TELEGRAM_GROUP_ID
        # es un supergrupo forum, cada categoría se enruta a su topic por message_thread_id.
        self.chat_id_sports = os.getenv("TELEGRAM_CHAT_ID_SPORTS", "") or self.chat_id
        self.chat_id_crypto = os.getenv("TELEGRAM_CHAT_ID_CRYPTO", "") or self.chat_id
        self.group_id = os.getenv("TELEGRAM_GROUP_ID", "") or self.chat_id
        self.topic_sports = os.getenv("TELEGRAM_TOPIC_SPORTS", "")
        self.topic_crypto = os.getenv("TELEGRAM_TOPIC_CRYPTO", "")
        self._chat_ids = {
            "sports": self.chat_id_sports,
            "crypto": self.chat_id_crypto,
        }
        self._topics = {
            "sports": self.topic_sports,
            "crypto": self.topic_crypto,
        }
        # Dedup: event_ids that already received an opportunity alert.
        # Auto-expire after 24h so old events don't permanently block.
        self._sent_event_alerts = BoundedTimeDict(max_size=500, ttl_seconds=86400)
        # Dedup por título normalizado: evita que diferentes workers (cross-platform,
        # sports arb, sniper) alerten el mismo partido con event_id distintos.
        self._sent_title_alerts = BoundedTimeDict(max_size=500, ttl_seconds=86400)
        # Dedup de resultados de resolución: un mismo evento solo se informa UNA vez
        # (TTL 30 días — estos mercados no re-resuelven en la práctica).
        self._sent_resolution_alerts = BoundedTimeDict(max_size=5000, ttl_seconds=2592000)
        # Rate limit global de envíos: evita spam de mensajes.
        self._min_send_interval = float(os.getenv("TELEGRAM_MIN_INTERVAL_SECONDS", "5"))
        self._next_allowed_send = 0.0
        self._send_lock = threading.Lock()
        # Polling state
        self._last_update_id = 0
        self._polling_task = None
        self._db = None
        self._engine = None
        # Reply context: set when handling a command so handlers reply in the
        # same chat/topic the command came from.
        self._reply_chat_id = None
        self._reply_thread_id = None

    def configure(self, db, engine):
        """Set DB and engine references for command handlers."""
        self._db = db
        self._engine = engine

    def _api_get(self, method: str, params: dict = None) -> dict | None:
        """Call Telegram Bot API GET method."""
        url = f"{self.base_url}/{method}"
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{query}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"[Telegram] API error {method}: {e}")
            return None

    async def start_polling(self):
        """Start polling for Telegram commands in background."""
        if not self.enabled:
            return
        self._polling_task = asyncio.create_task(self._poll_loop())
        print("[Telegram] Command polling started")

    async def _poll_loop(self):
        """Poll Telegram getUpdates for incoming commands."""
        while True:
            try:
                result = self._api_get("getUpdates", {
                    "offset": str(self._last_update_id + 1),
                    "timeout": "10",
                    "allowed_updates": '["message"]',
                })
                if result and result.get("ok"):
                    for update in result.get("result", []):
                        self._last_update_id = update["update_id"]
                        msg = update.get("message", {})
                        chat_id = str(msg.get("chat", {}).get("id", ""))
                        text = msg.get("text", "").strip()
                        thread_id = msg.get("message_thread_id")
                        # Log ALL incoming messages so we can capture chat_id /
                        # message_thread_id from group topics (setup helper).
                        if chat_id and text:
                            print(
                                f"[Telegram] Msg chat={chat_id} thread={thread_id} "
                                f"text={text[:60]!r}"
                            )
                        # Only respond to authorized chats: DM principal o el
                        # supergrupo forum (topics).
                        authorized = (chat_id == self.chat_id) or (
                            self.group_id and chat_id == self.group_id
                        )
                        if authorized and text.startswith("/"):
                            await self._handle_command(
                                text, chat_id=chat_id, message_thread_id=thread_id
                            )
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Telegram] Poll error: {e}")
            await asyncio.sleep(2)

    async def _handle_command(self, text: str, chat_id: str = None, message_thread_id=None):
        """Route commands to handlers. Replies go to the chat/topic the command
        came from (works inside group forum topics)."""
        cmd = text.split()[0].lower().split("@")[0]  # Remove @botname if present
        handlers = {
            "/status": self._cmd_status,
            "/workers": self._cmd_workers,
            "/positions": self._cmd_positions,
            "/pnl": self._cmd_pnl,
            "/sports": self._cmd_sports,
            "/help": self._cmd_help,
        }
        handler = handlers.get(cmd)
        if handler:
            # Reply context: handlers call send_message() with no chat_id → reply
            # in the same chat (and topic) the command arrived from.
            self._reply_chat_id = chat_id or self.chat_id
            self._reply_thread_id = self._topic_thread_id(chat_id, message_thread_id)
            try:
                handler()
            finally:
                self._reply_chat_id = None
                self._reply_thread_id = None
        else:
            self._reply_chat_id = chat_id or self.chat_id
            self._reply_thread_id = self._topic_thread_id(chat_id, message_thread_id)
            try:
                self.send_message(f"❓ Comando desconocido: <code>{cmd}</code>\nUsa /help para ver comandos disponibles.")
            finally:
                self._reply_chat_id = None
                self._reply_thread_id = None

    def _cmd_help(self):
        """Show available commands."""
        self.send_message(
            "📋 <b>Comandos disponibles</b>\n\n"
            "/status — Estado de todos los workers\n"
            "/workers — Lista de workers\n"
            "/positions — Posiciones abiertas\n"
            "/pnl — Resumen de P&L\n"
            "/sports — Eventos deportivos monitoreados\n"
            "/help — Esta ayuda"
        )

    def _cmd_status(self):
        """Show system status summary."""
        if not self._engine or not self._db:
            self.send_message("⚠️ Engine no configurado")
            return
        try:
            workers = self._engine.workers
            active = sum(1 for w in workers.values() if w.is_running)
            total = len(workers)
            positions = self._db.get_open_positions(worker_id=None) or []
            lines = [
                f"📊 <b>Estado del Sistema</b>",
                f"",
                f"<b>Workers:</b> {active}/{total} activos",
                f"<b>Posiciones abiertas:</b> {len(positions)}",
                f"",
            ]
            for wid, w in workers.items():
                status = "✅" if w.is_running else "❌"
                lines.append(f"{status} <b>{w.name}</b> — {w.symbol}")
            self.send_message("\n".join(lines))
        except Exception as e:
            self.send_message(f"⚠️ Error: {e}")

    def _cmd_workers(self):
        """Show detailed workers list."""
        if not self._engine:
            self.send_message("⚠️ Engine no configurado")
            return
        try:
            workers = self._engine.workers
            lines = ["👥 <b>Workers</b>\n"]
            for wid, w in workers.items():
                status = "🟢" if w.is_running else "🔴"
                lines.append(
                    f"{status} <b>{w.name}</b>\n"
                    f"   ID: <code>{wid}</code>\n"
                    f"   Símbolo: {w.symbol}\n"
                    f"   Feeder: {w.feeder_type}\n"
                )
            self.send_message("\n".join(lines))
        except Exception as e:
            self.send_message(f"⚠️ Error: {e}")

    def _cmd_sports(self):
        """Show sports events currently being monitored."""
        try:
            from src.strategy.sports_arb import _sports_edge_data
        except Exception as e:
            self.send_message(f"⚠️ Error: {e}")
            return
        if not _sports_edge_data:
            self.send_message("⚽ No hay eventos deportivos en el radar")
            return
        items = sorted(
            _sports_edge_data.items(),
            key=lambda kv: kv[1].get("edge", 0) or 0,
            reverse=True,
        )
        lines = [f"⚽ <b>Eventos deportivos monitoreados</b> ({len(items)})\n"]
        for event_id, info in items:
            title = info.get("title") or event_id
            edge = info.get("edge", 0) or 0
            total_yes = info.get("total_yes", 0) or 0
            outcomes = info.get("outcomes_count", 0) or 0
            arrow = "🟢" if edge > 0 else "⚪"
            lines.append(
                f"{arrow} <b>{title}</b>\n"
                f"   edge {edge * 100:.1f}% | total_yes {total_yes:.3f} | {outcomes} outcomes\n"
            )
        self.send_message("\n".join(lines))

    def _cmd_positions(self):
        """Show open positions."""
        if not self._db:
            self.send_message("⚠️ DB no configurada")
            return
        try:
            positions = self._db.get_open_positions(worker_id=None) or []
            if not positions:
                self.send_message("📭 No hay posiciones abiertas")
                return
            lines = ["📊 <b>Posiciones Abiertas</b>\n"]
            for p in positions[:10]:  # Limit to 10
                lines.append(
                    f"• <b>{p.get('symbol', 'N/A')}</b>\n"
                    f"  {p.get('side', '?')} @ ${p.get('entry_price', 0):.4f}\n"
                    f"  Worker: {p.get('worker_id', '?')}\n"
                )
            if len(positions) > 10:
                lines.append(f"... y {len(positions) - 10} más")
            self.send_message("\n".join(lines))
        except Exception as e:
            self.send_message(f"⚠️ Error: {e}")

    def _cmd_pnl(self):
        """Show P&L summary."""
        if not self._db:
            self.send_message("⚠️ DB no configurada")
            return
        try:
            summary = self._db.get_pnl_summary(worker_id=None) or {}
            total_pnl = summary.get("total_pnl", 0)
            win_rate = summary.get("win_rate_pct", 0)
            total_trades = summary.get("total_trades", 0)
            winning = summary.get("winning_trades", 0)
            losing = summary.get("losing_trades", 0)
            icon = "💰" if total_pnl >= 0 else "📉"
            self.send_message(
                f"{icon} <b>Resumen P&L</b>\n\n"
                f"<b>Total:</b> ${total_pnl:.2f}\n"
                f"<b>Trades:</b> {total_trades} (W:{winning} L:{losing})\n"
                f"<b>Win Rate:</b> {win_rate:.1f}%\n"
                f"<b>Profit Factor:</b> {summary.get('profit_factor', 0):.2f}\n"
                f"<b>Mejor trade:</b> ${summary.get('best_trade', 0):.2f}\n"
                f"<b>Peor trade:</b> ${summary.get('worst_trade', 0):.2f}"
            )
        except Exception as e:
            self.send_message(f"⚠️ Error: {e}")

    def _resolve_chat_id(self, category: str = None) -> str:
        """Retorna el chat_id correspondiente a la categoría (sub-sala).

        sports -> TELEGRAM_CHAT_ID_SPORTS (fallback: TELEGRAM_CHAT_ID)
        crypto -> TELEGRAM_CHAT_ID_CRYPTO (fallback: TELEGRAM_CHAT_ID)
        """
        if category:
            cat = category.lower()
            if cat in self._chat_ids and self._chat_ids[cat]:
                return self._chat_ids[cat]
        return self.chat_id

    def _resolve_target(self, category: str = None):
        """Retorna (chat_id, message_thread_id) para una categoría.

        Si hay un supergrupo forum (TELEGRAM_GROUP_ID) y el topic de la categoría
        está configurado (TELEGRAM_TOPIC_SPORTS/CRYPTO), envía al topic del grupo.
        Si no, usa el chat dedicado por categoría (TELEGRAM_CHAT_ID_SPORTS/CRYPTO)
        o el chat principal como fallback.
        """
        cat = (category or "").lower()
        # Topics: prioridad si el grupo es un forum y hay topic configurado.
        if self.group_id and cat in self._topics and self._topics[cat]:
            try:
                thread_id = int(self._topics[cat])
                return self.group_id, thread_id
            except (TypeError, ValueError):
                pass
        return self._resolve_chat_id(category), None

    def _topic_thread_id(self, chat_id: str, message_thread_id=None):
        """Solo se usa message_thread_id si el chat es un supergrupo (forum).

        En DM privado o chat normal, message_thread_id debe omitirse.
        """
        if message_thread_id and str(chat_id).startswith("-100"):
            return message_thread_id
        return None

    def send_message(self, text: str, parse_mode: str = "HTML", chat_id: str = None, message_thread_id=None) -> bool:
        """Send a message to the configured chat (or a specific chat_id/topic).

        Si chat_id es None, responde en el chat/topic del comando que se está
        manejando (reply context) o en el chat principal.
        """
        if not self.enabled:
            return False

        target = chat_id or self._reply_chat_id or self.chat_id
        thread_id = message_thread_id
        if thread_id is None and chat_id is None:
            thread_id = self._reply_thread_id

        # Rate limit: skip envíos más frecuentes que el intervalo mínimo.
        # Se implementa como "skip" (no sleep) para no bloquear el event loop.
        # Se aplica SOLO a envíos espontáneos (alertas): las respuestas a comandos
        # (reply context activo) siempre se envían.
        if self._reply_chat_id is None:
            now = time.time()
            with self._send_lock:
                if now < self._next_allowed_send:
                    return False
                self._next_allowed_send = now + self._min_send_interval
        
        payload = {
            "chat_id": target,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        if thread_id is not None:
            payload["message_thread_id"] = thread_id

        try:
            data = json.dumps(payload).encode("utf-8")
            
            req = urllib.request.Request(
                f"{self.base_url}/sendMessage",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                result = json.loads(r.read().decode("utf-8"))
                return result.get("ok", False)
        except Exception as e:
            print(f"[Telegram] Error sending message: {e}")
            return False
    
    def has_been_alerted(self, event_id: str) -> bool:
        """Check if an opportunity alert was already sent for this event_id.

        Fast-path: in-memory cache. Authoritative: telegram_dedup table
        (survives container restarts).
        """
        if self._sent_event_alerts.get(event_id) is not None:
            return True
        if self._db and self._db.has_telegram_alert_been_sent(event_id, "opportunity"):
            self._sent_event_alerts[event_id] = time.time()
            return True
        return False

    def mark_alerted(self, event_id: str):
        """Mark an event_id as having received an opportunity alert."""
        self._sent_event_alerts[event_id] = time.time()
        if self._db:
            self._db.mark_telegram_alert_sent(event_id, "opportunity")

    def clear_alerted(self, event_id: str):
        """Clear an event_id after resolution — allows new alert if event reopens."""
        self._sent_event_alerts.discard(event_id)

    @staticmethod
    def _normalize_title(title: str) -> str:
        """Normaliza un título de evento para dedup cross-worker.

        Ejemplo: "Diana Shnaider Vs Iga Swiatek - Moneyline" → "diana shnaider vs iga swiatek"
        Elimina sub-mercados (moneyline, spread, total, sets, games, over, under)
        y normaliza a minúsculas para que diferentes workers usen la misma clave.
        """
        import re
        t = title.lower().strip()
        # Eliminar sufijos de sub-mercado comunes
        for suffix in ["moneyline", "spread", "total", "over", "under",
                       "3 or more total sets", "2 or more total sets",
                       "22 or more total games", "20 or more total games",
                       "both teams to score", "clean sheet"]:
            t = t.replace(suffix, "")
        # Normalizar espacios
        t = re.sub(r"\s+", " ", t).strip()
        # Eliminar trailing separators
        t = t.rstrip(" -–—:·")
        return t

    def _title_already_alerted(self, title: str) -> bool:
        """Check if a normalized title was already alerted (cross-worker dedup)."""
        norm = self._normalize_title(title)
        if not norm:
            return False
        return self._sent_title_alerts.get(norm) is not None

    def _mark_title_alerted(self, title: str):
        """Mark a normalized title as alerted."""
        norm = self._normalize_title(title)
        if norm:
            self._sent_title_alerts[norm] = time.time()

    def has_resolution_alerted(self, event_id: str) -> bool:
        """True si ya se envió el resultado de resolución para este evento.

        Fast-path: in-memory cache. Authoritative: telegram_dedup table.
        """
        if self._sent_resolution_alerts.get(event_id) is not None:
            return True
        if self._db and self._db.has_telegram_alert_been_sent(event_id, "resolution"):
            self._sent_resolution_alerts[event_id] = time.time()
            return True
        return False

    def mark_resolution_alerted(self, event_id: str):
        """Mark a resolution alert as sent (memory + DB)."""
        self._sent_resolution_alerts[event_id] = time.time()
        if self._db:
            self._db.mark_telegram_alert_sent(event_id, "resolution")

    def send_alert(self, alert_type: str, message: str, event_id: str = None, category: str = None):
        """Send a formatted alert. If event_id is provided, deduplicates.
        category routes the alert to the sub-room/topic (sports/crypto)."""
        # Dedup: skip if already alerted for this event (except resolution results)
        if event_id and alert_type == "opportunity":
            if self.has_been_alerted(event_id):
                return False
            self.mark_alerted(event_id)
        
        icons = {
            "opportunity": "🎯",
            "trade": "✅",
            "error": "⚠️",
            "warning": "⚠️",
            "info": "ℹ️",
            "profit": "💰",
            "loss": "📉",
            "system": "🔧"
        }
        icon = icons.get(alert_type, "📢")
        timestamp = datetime.now().strftime("%H:%M:%S")
        text = f"{icon} [{timestamp}] {message}"
        
        # Resolution results (profit/loss) always clear the dedup
        if event_id and alert_type in ("profit", "loss"):
            self.clear_alerted(event_id)
        
        target, thread_id = self._resolve_target(category)
        return self.send_message(text, chat_id=target, message_thread_id=thread_id)
    
    def send_daily_report(self, stats: dict):
        """Send a daily summary report."""
        text = f"""📊 <b>Reporte Diario</b>

<b>Oportunidades:</b> {stats.get('opportunities', 0)}
<b>Trades ejecutados:</b> {stats.get('trades', 0)}
<b>P&L:</b> ${stats.get('pnl', 0):.2f}
<b>Edge promedio:</b> {stats.get('avg_edge', 0):.2f}%

<b>Workers activos:</b> {stats.get('active_workers', 0)}/{stats.get('total_workers', 0)}
<b>Errores:</b> {stats.get('errors', 0)}"""
        return self.send_message(text)
    
    def send_opportunity(self, event: str, edge: float, platform_a: str, platform_b: str, event_id: str = None, category: str = None, worker_id: str = None, legs_detail: str = None):
        """Send an opportunity alert with dedup, routed to the category sub-room."""
        # Dedup por event_id (mismo slug/market)
        if event_id and self.has_been_alerted(event_id):
            return False
        # Dedup por título normalizado (mismo partido detectado por workers distintos)
        # Usar tanto event como event_id para cubrir ambos casos:
        # - sports_arb pasa título legible ("LP, Santa Clara vs Nacional")
        # - cross_platform_arb pasa slug ("match_nacional-vs-santa-clara__...")
        if self._title_already_alerted(event):
            return False
        if event_id and self._title_already_alerted(event_id):
            return False
        if event_id:
            self.mark_alerted(event_id)
        self._mark_title_alerted(event)
        if event_id:
            self._mark_title_alerted(event_id)
        
        # Format clean ID display from event_id or slug
        event_ref = event_id if event_id else "N/A"
        if event_ref.startswith("limitless_crypto_"):
            event_ref = event_ref[len("limitless_crypto_"):]
            
        legs_block = f"\n{legs_detail}" if legs_detail else ""
        text = f"""🎯 <b>Oportunidad Detectada</b>

<b>Worker:</b> {worker_id or 'N/A'}
<b>Evento:</b> {event}
<b>Contrato / ID:</b> <code>{event_ref}</code>
<b>Edge:</b> {edge:.2f}%
<b>Plataformas:</b> {platform_a} ↔ {platform_b}{legs_block}
<b>Sala:</b> {category or 'general'}
<b>Hora:</b> {datetime.now().strftime("%H:%M:%S")}"""
        target, thread_id = self._resolve_target(category)
        return self.send_message(text, chat_id=target, message_thread_id=thread_id)
    
    def send_opportunity_resolution(self, event_id: str, event_title: str, winning_outcome: str, entry_price: float, expected_profit: float, position_won: bool = None, position_pnl: float = None, category: str = None):
        """Send a dedicated resolution report showing if the paper trade / fish opportunity won or lost."""
        event_ref = event_id if event_id else "N/A"
        if event_ref.startswith("limitless_crypto_"):
            event_ref = event_ref[len("limitless_crypto_"):]
            
        # Dedup de resolución: un mismo evento solo se informa UNA vez.
        # Evita mensajes repetidos con el mismo código cuando el mercado se re-verifica.
        if event_id:
            if self.has_resolution_alerted(event_id):
                return False
            self.mark_resolution_alerted(event_id)

        # Clear opportunity dedup memory for this event (permite re-alertar si reabre)
        if event_id:
            self.clear_alerted(event_id)

        # Si conocemos si nuestra pata ganó, mostrarlo con precisión
        if position_won is not None:
            icon = "💰 <b>[GANASTE]</b>" if position_won else "📉 <b>[PERDISTE]</b>"
            pnl_line = f"<b>P&L:</b> {'+' if position_pnl and position_pnl > 0 else ''}${position_pnl:.4f}"
        else:
            is_hit = winning_outcome in ("YES", "NO")
            icon = "🎉 <b>[ACIERTO]</b>" if is_hit else "❌ <b>[SIN RESOLVER / SPLIT]</b>"
            pnl_line = f"<b>Ganancia Teórica ($1.00 - Costo):</b> +${expected_profit:.4f}"
        
        text = f"""🏁 <b>Resultado del Evento</b>

{icon}
<b>Contrato / ID:</b> <code>{event_ref}</code>
<b>Evento:</b> {event_title or event_ref}
<b>Resultado Ganador:</b> {winning_outcome}
<b>Costo de Entrada:</b> ${entry_price:.4f}
{pnl_line}
<b>Sala:</b> {category or 'general'}
<b>Hora de Cierre:</b> {datetime.now().strftime("%H:%M:%S")}"""
        target, thread_id = self._resolve_target(category)
        return self.send_message(text, chat_id=target, message_thread_id=thread_id)
    
    def send_trade_executed(self, event: str, side: str, price: float, amount: float):
        """Send a trade execution alert."""
        text = f"""✅ <b>Trade Ejecutado</b>

<b>Evento:</b> {event}
<b>Lado:</b> {side}
<b>Precio:</b> ${price:.4f}
<b>Monto:</b> ${amount:.2f}
<b>Hora:</b> {datetime.now().strftime("%H:%M:%S")}"""
        return self.send_message(text)
    
    def send_error(self, error: str, worker_id: str = ""):
        """Send an error alert."""
        text = f"""⚠️ <b>Error</b>

<b>Worker:</b> {worker_id or 'Sistema'}
<b>Error:</b> {error}
<b>Hora:</b> {datetime.now().strftime("%H:%M:%S")}"""
        return self.send_message(text)
    
    def send_worker_status(self, workers: list):
        """Send worker status update."""
        lines = ["📋 <b>Estado de Workers</b>\n"]
        for w in workers:
            status = "✅" if w.get("is_running") else "❌"
            lines.append(f"{status} <b>{w.get('name')}</b>: {w.get('symbol', 'N/A')}")
        text = "\n".join(lines)
        return self.send_message(text)
    
    def send_balance(self, balances: dict):
        """Send balance information."""
        text = f"""💰 <b>Balances</b>

<b>Limitless:</b> ${balances.get('limitless', 0):.2f}
<b>Kalshi:</b> ${balances.get('kalshi', 0):.2f}
<b>Total:</b> ${balances.get('total', 0):.2f}"""
        return self.send_message(text)
    
    def send_positions(self, positions: list):
        """Send open positions."""
        if not positions:
            return self.send_message("📭 No hay posiciones abiertas")
        
        lines = ["📊 <b>Posiciones Abiertas</b>\n"]
        for p in positions:
            lines.append(f"• {p.get('symbol', 'N/A')}: {p.get('side', '?')} @ ${p.get('entry_price', 0):.4f}")
        text = "\n".join(lines)
        return self.send_message(text)


# Singleton instance
telegram_bot = TelegramBot()
