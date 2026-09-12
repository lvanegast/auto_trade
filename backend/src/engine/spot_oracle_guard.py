"""
SpotOracleGuard — Protección matemática y oracular contra Adverse Selection en prediction markets.

Evita la trampa del Resolution Sniper (comprar contratos a 0.98 pre-settlement
cuando el precio spot subyacente está demasiado cerca del strike, generando un EV negativo).

Implementa:
1. Extracción de Strike y Activo Base desde metadata/descripción/título de Limitless.
2. Consulta de precio spot en tiempo real (BinanceTracker WS con fallback REST).
3. Cálculo de Z-Score dinámico normalizado por volatilidad y tiempo restante:
   Z = (|Spot - Strike| / Strike) / (sigma_1h * sqrt(t_rem))
"""

import math
import re
import time
import urllib.request
import json
import logging
from typing import Tuple, Optional

logger = logging.getLogger("SpotOracleGuard")


class SpotOracleGuard:
    # Volatilidad horaria típica por activo (1 sigma)
    VOLATILITY_1H = {
        # Crypto
        "BTC": 0.0035,   # 0.35% / hr
        "ETH": 0.0050,   # 0.50% / hr
        "SOL": 0.0080,   # 0.80% / hr
        "BNB": 0.0060,   # 0.60% / hr
        "XRP": 0.0080,   # 0.80% / hr
        "DOGE": 0.0100,  # 1.00% / hr
        # Equities & Commodities (Finance)
        "TSLA": 0.0060,  # 0.60% / hr
        "NVDA": 0.0060,  # 0.60% / hr
        "META": 0.0040,  # 0.40% / hr
        "AAPL": 0.0030,  # 0.30% / hr
        "GOOGL": 0.0030, # 0.30% / hr
        "GOOG": 0.0030,  # 0.30% / hr
        "SPY": 0.0015,   # 0.15% / hr
        "OXY": 0.0040,   # 0.40% / hr
        "ITA": 0.0025,   # 0.25% / hr
        "LMT": 0.0025,   # 0.25% / hr
        "SPCX": 0.0050,  # 0.50% / hr
        "PAXG": 0.0020,  # 0.20% / hr
        "GOLD": 0.0020,  # 0.20% / hr
    }
    DEFAULT_VOLATILITY = 0.0075

    # Cache en memoria para consultas REST (TTL = 4 segundos)
    _rest_cache: dict = {}

    @classmethod
    def extract_market_info(cls, market: object) -> Tuple[str, Optional[float]]:
        """
        Extrae el símbolo del activo base (BTC, ETH, TSLA, NVDA, etc.) y el strike/openPrice.
        Soporta objetos de limitless_sdk o diccionarios.
        """
        slug = getattr(market, "slug", "") or (market.get("slug", "") if isinstance(market, dict) else "")
        title = getattr(market, "title", "") or (market.get("title", "") if isinstance(market, dict) else "")
        desc = getattr(market, "description", "") or (market.get("description", "") if isinstance(market, dict) else "")
        metadata = getattr(market, "metadata", None) or (market.get("metadata") if isinstance(market, dict) else {})

        # 1. Identificar activo
        asset = "UNKNOWN"
        check_str = f"{slug} {title}".upper()
        
        KNOWN_SYMBOLS = [
            # Crypto
            "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "HYPE",
            # Equities / Finance
            "TSLA", "NVDA", "AAPL", "SPY", "META", "GOOGL", "GOOG", "OXY", "ITA", "LMT", "SPCX", "PAXG", "GOLD"
        ]
        for sym in KNOWN_SYMBOLS:
            if f"({sym})" in check_str or f" {sym} " in f" {check_str} " or f"{sym.lower()}-" in slug.lower():
                asset = sym
                break

        # 2. Identificar strike/openPrice
        strike_price = None
        if isinstance(metadata, dict):
            op = metadata.get("openPrice")
            if op:
                try:
                    strike_price = float(str(op).rstrip("."))
                except (ValueError, TypeError):
                    pass

        if strike_price is None and desc:
            # Buscar en la descripción patrones como "captured on ... was $2487.80" o "Price to Beat captured ... was $2487.80"
            m = re.search(r"(?:Price to Beat captured|captured on)[^$]*\$([0-9,.]+)", desc)
            if m:
                try:
                    cleaned = m.group(1).replace(",", "").rstrip(".")
                    strike_price = float(cleaned)
                except (ValueError, TypeError):
                    pass

        return asset, strike_price

    @classmethod
    def get_spot_price(cls, asset: str) -> Optional[float]:
        """
        Obtiene el precio spot en tiempo real para un activo (Crypto o Acciones de Wall Street).
        - Para Crypto: BinanceTracker WS / Binance REST.
        - Para PAXG / Gold: Binance REST (PAXGUSDT).
        - Para Acciones (TSLA, NVDA, AAPL, SPY, etc.): Yahoo Finance API v8 con cache.
        """
        asset_norm = asset.strip().upper().replace("USDT", "")
        if not asset_norm or asset_norm == "UNKNOWN":
            return None

        # Normalizar GOLD -> PAXG
        if asset_norm == "GOLD":
            asset_norm = "PAXG"

        now = time.time()
        cached = cls._rest_cache.get(asset_norm)
        if cached and (now - cached[0]) < 3.5:
            return cached[1]

        # 1. Intentar desde BinanceTracker (para crypto)
        try:
            from src.strategy.lead_lag_arbitrage import BinanceTracker
            price = BinanceTracker.get_price(asset_norm)
            if price > 0:
                return price
        except Exception:
            pass

        # 2. Si es PAXG o Crypto conocida, consultar Binance REST
        if asset_norm in ("PAXG", "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"):
            try:
                url = f"https://api.binance.com/api/v3/ticker/price?symbol={asset_norm}USDT"
                req = urllib.request.Request(url, headers={"User-Agent": "AutoTradeBot/1.0"})
                with urllib.request.urlopen(req, timeout=2.5) as response:
                    data = json.loads(response.read().decode())
                    p = float(data.get("price", 0.0))
                    if p > 0:
                        cls._rest_cache[asset_norm] = (now, p)
                        return p
            except Exception as e:
                logger.warning(f"Error consultando spot Binance REST para {asset_norm}: {e}")

        # 3. Para acciones de Wall Street (TSLA, NVDA, AAPL, SPY, META, GOOGL, etc.)
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{asset_norm}?interval=1m"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=2.5) as response:
                data = json.loads(response.read().decode())
                meta = data["chart"]["result"][0]["meta"]
                p = float(meta.get("regularMarketPrice", 0.0))
                if p > 0:
                    cls._rest_cache[asset_norm] = (now, p)
                    return p
        except Exception as e:
            logger.warning(f"Error consultando spot Yahoo Finance para {asset_norm}: {e}")

        return None

    @classmethod
    def evaluate_safety(
        cls,
        asset: str,
        spot_price: float,
        strike_price: float,
        side: str,
        remaining_seconds: float,
        category: str = "crypto",
    ) -> Tuple[bool, float, float, str]:
        """
        Evalúa si la compra pre-settlement tiene margen de seguridad estadístico.

        Returns:
            (is_safe: bool, z_score: float, delta_pct: float, reason: str)
        """
        if spot_price <= 0 or strike_price <= 0:
            return False, 0.0, 0.0, "Precios spot o strike inválidos"

        # Protección estricta para Finance (Acciones de Wall Street):
        # 1. Prohibido entrar con más de 300s (5 min) restantes para evitar la volatilidad de Power Hour / MOC.
        if category == "finance":
            if remaining_seconds > 300:
                return (
                    False,
                    0.0,
                    0.0,
                    f"Tiempo restante excesivo para acciones: {remaining_seconds:.0f}s > 300s (evitar Power Hour/MOC)",
                )

        asset_norm = asset.upper()
        sigma_1h = cls.VOLATILITY_1H.get(asset_norm, cls.DEFAULT_VOLATILITY)

        # Tiempo en horas con piso de 30s
        t_hours = max(remaining_seconds, 30.0) / 3600.0
        sigma_t = sigma_1h * math.sqrt(t_hours)

        delta = spot_price - strike_price
        delta_pct = delta / strike_price

        # Umbrales según categoría y tiempo restante
        if category == "finance":
            # Para acciones exigimos Z >= 3.0 y margen mínimo de 0.50%
            min_z = 3.0
            min_margin = 0.0050
        elif remaining_seconds > 600:
            min_z = 3.0
            min_margin = 0.0050  # 0.50%
        elif remaining_seconds > 300:
            min_z = 2.5
            min_margin = 0.0035  # 0.35%
        else:
            min_z = 2.0
            min_margin = 0.0020  # 0.20%

        side_upper = side.upper()
        if side_upper == "YES":
            # Para YES (Up), el spot DEBE estar por encima del strike
            if delta <= 0:
                return (
                    False,
                    0.0,
                    delta_pct,
                    f"Pérdida inminente: Spot ${spot_price:.2f} <= Strike ${strike_price:.2f} (delta={delta_pct*100:.3f}%)",
                )
            z = delta_pct / sigma_t
            if z < min_z or delta_pct < min_margin:
                return (
                    False,
                    z,
                    delta_pct,
                    f"Riesgo de Reversión Alto: Z={z:.2f} < {min_z} o delta={delta_pct*100:.3f}% < {min_margin*100:.2f}%",
                )
            return (
                True,
                z,
                delta_pct,
                f"OK Seguro: Z={z:.2f} >= {min_z}, delta={delta_pct*100:+.3f}% (Spot ${spot_price:.2f} vs Strike ${strike_price:.2f})",
            )

        elif side_upper == "NO":
            # Para NO (Down), el spot DEBE estar por debajo del strike
            if delta >= 0:
                return (
                    False,
                    0.0,
                    delta_pct,
                    f"Pérdida inminente: Spot ${spot_price:.2f} >= Strike ${strike_price:.2f} (delta={delta_pct*100:+.3f}%)",
                )
            abs_delta_pct = abs(delta_pct)
            z = abs_delta_pct / sigma_t
            if z < min_z or abs_delta_pct < min_margin:
                return (
                    False,
                    z,
                    delta_pct,
                    f"Riesgo de Reversión Alto: Z={z:.2f} < {min_z} o |delta|={abs_delta_pct*100:.3f}% < {min_margin*100:.2f}%",
                )
            return (
                True,
                z,
                delta_pct,
                f"OK Seguro: Z={z:.2f} >= {min_z}, |delta|={abs_delta_pct*100:+.3f}% (Spot ${spot_price:.2f} vs Strike ${strike_price:.2f})",
            )

        return False, 0.0, 0.0, f"Lado desconocido {side}"
