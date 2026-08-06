"""
Telegram Bot for AutoTrade — Alerts and Commands

Sends real-time alerts and responds to user commands.
Works on both local and Railway deployments.
"""

import os
import json
import asyncio
import urllib.request
from datetime import datetime


class TelegramBot:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.enabled = bool(self.token and self.chat_id)
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        
    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the configured chat."""
        if not self.enabled:
            return False
        
        try:
            data = json.dumps({
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }).encode("utf-8")
            
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
    
    def send_alert(self, alert_type: str, message: str):
        """Send a formatted alert."""
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
        return self.send_message(text)
    
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
    
    def send_opportunity(self, event: str, edge: float, platform_a: str, platform_b: str):
        """Send an opportunity alert."""
        text = f"""🎯 <b>Oportunidad Detectada</b>

<b>Evento:</b> {event}
<b>Edge:</b> {edge:.2f}%
<b>Plataformas:</b> {platform_a} ↔ {platform_b}
<b>Hora:</b> {datetime.now().strftime("%H:%M:%S")}"""
        return self.send_message(text)
    
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
