"""
Configuración de pares de mercados cross-platform para arbitraje Kalshi ↔ Limitless Exchange.

Cada par define el mismo evento real listado en ambas plataformas con IDs diferentes.
Los precios en ambos platforms son binarios [0.0, 1.0] representando probabilidad YES.

Limitless usa slugs (URL-friendly IDs), Kalshi usa tickers.
"""

# Cada par tiene:
#   event_id:              identificador lógico del evento
#   event_label:           nombre legible para UI
#   kalshi_ticker:         ticker del contrato YES en Kalshi (production)
#   limitless_slug:        slug del submarket en Limitless Exchange
#   category:              agrupación para UI (Fed, Macro, Crypto, etc.)
#   expiration:            fecha de expiración ISO 8601

MARKET_PAIRS = [
    {
        "event_id": "fed_rate_july_2026",
        "event_label": "FED recorte tasa Julio 2026",
        "kalshi_ticker": "FEDRATE-26JUL",
        "limitless_slug": "july-meeting-1779881657546",
        "limitless_group_slug": "fed-rate-cut-by-1779881657530",
        "category": "Fed",
        "expiration": "2026-07-29T00:00:00Z",
    },
    {
        "event_id": "fed_rate_sept_2026",
        "event_label": "FED recorte tasa Sept 2026",
        "kalshi_ticker": "FEDRATE-26SEP",
        "limitless_slug": "september-meeting-1779881657549",
        "limitless_group_slug": "fed-rate-cut-by-1779881657530",
        "category": "Fed",
        "expiration": "2026-09-16T00:00:00Z",
    },
    {
        "event_id": "fed_rate_oct_2026",
        "event_label": "FED recorte tasa Oct 2026",
        "kalshi_ticker": "FEDRATE-26OCT",
        "limitless_slug": "october-meeting-1779881657552",
        "limitless_group_slug": "fed-rate-cut-by-1779881657530",
        "category": "Fed",
        "expiration": "2026-10-28T00:00:00Z",
    },
    {
        "event_id": "fed_rate_dec_2026",
        "event_label": "FED recorte tasa Dec 2026",
        "kalshi_ticker": "FEDRATE-26DEC",
        "limitless_slug": "december-meeting-1779881657556",
        "limitless_group_slug": "fed-rate-cut-by-1779881657530",
        "category": "Fed",
        "expiration": "2026-12-09T00:00:00Z",
    },
    {
        "event_id": "us_recession_2026",
        "event_label": "Recesión EEUU 2026",
        "kalshi_ticker": "RECESSION-26",
        "limitless_slug": "us-recession-by-end-of-2026-1767804297592",
        "limitless_group_slug": None,
        "category": "Macro",
        "expiration": "2026-12-31T23:59:59Z",
    },
    {
        "event_id": "core_pce_june_2026",
        "event_label": "Core PCE YoY Junio 2026",
        "kalshi_ticker": "PCE-26JUN",
        "limitless_slug": "core-pce-yoy-june-2026-1784042260443",
        "limitless_group_slug": None,
        "category": "Macro",
        "expiration": "2026-07-31T00:00:00Z",
    },
    {
        "event_id": "us_gdp_q2_2026",
        "event_label": "US GDP Q2 2026",
        "kalshi_ticker": "GDP-Q2-26",
        "limitless_slug": "us-gdp-growth-in-q2-2026-1777901322288",
        "limitless_group_slug": None,
        "category": "Macro",
        "expiration": "2026-09-30T00:00:00Z",
    },
    {
        "event_id": "house_2026",
        "event_label": "¿Quién gana la Cámara 2026?",
        "kalshi_ticker": "HOUSE-26",
        "limitless_slug": "which-party-will-win-the-house-in-2026-1769088464314",
        "limitless_group_slug": None,
        "category": "Politics",
        "expiration": "2026-11-03T00:00:00Z",
    },
    {
        "event_id": "president_2028",
        "event_label": "Presidente EEUU 2028",
        "kalshi_ticker": "PRES-28",
        "limitless_slug": "presidential-election-winner-2028-1769010522121",
        "limitless_group_slug": None,
        "category": "Politics",
        "expiration": "2028-11-07T00:00:00Z",
    },
    {
        "event_id": "dxy_july_2026",
        "event_label": "DXY Dollar Index Julio 2026",
        "kalshi_ticker": "DXY-26JUL",
        "limitless_slug": "which-price-will-dxy-hit-in-july-1782892249118",
        "limitless_group_slug": None,
        "category": "Macro",
        "expiration": "2026-07-31T00:00:00Z",
    },
]


def get_pair_by_kalshi_ticker(ticker: str) -> dict | None:
    for pair in MARKET_PAIRS:
        if pair["kalshi_ticker"] == ticker:
            return pair
    return None


def get_pair_by_limitless_slug(slug: str) -> dict | None:
    for pair in MARKET_PAIRS:
        if pair["limitless_slug"] == slug or pair.get("limitless_group_slug") == slug:
            return pair
    return None


def get_pair_by_event_id(event_id: str) -> dict | None:
    for pair in MARKET_PAIRS:
        if pair["event_id"] == event_id:
            return pair
    return None


def get_active_pairs() -> list[dict]:
    return [p for p in MARKET_PAIRS if p["limitless_slug"] is not None]


def get_fed_pairs() -> list[dict]:
    return [p for p in MARKET_PAIRS if p["category"] == "Fed"]
