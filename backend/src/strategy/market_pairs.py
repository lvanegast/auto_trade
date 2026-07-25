"""
Catálogo versionado de pares de mercados cross-platform para arbitraje.

Cada par define el mismo evento real listado en ambas plataformas (Kalshi ↔ Limitless).
Versión: incluye regla de resolución exacta, zona horaria, umbral, moneda y restricciones.

Una similitud de títulos NO basta para cubrir arbitraje: la resolución debe ser idéntica.
"""

CATALOG_VERSION = "2.0.0"

MARKET_PAIRS = [
    {
        "event_id": "fed_rate_july_2026",
        "event_label": "FED recorte tasa Julio 2026",
        "kalshi_ticker": "FEDRATE-26JUL",
        "limitless_slug": "july-meeting-1779881657546",
        "limitless_group_slug": "fed-rate-cut-by-1779881657530",
        "category": "Fed",
        "expiration": "2026-07-29T00:00:00Z",
        "resolution": {
            "rule": "FOMC recorta la tasa federal funds en la reunión de julio 2026",
            "source": "Federal Reserve",
            "threshold": None,
            "currency": "USD",
            "timezone": "America/New_York",
            "exact_wording": "The Federal Open Market Committee lowers the target range for the federal funds rate at the July 29, 2026 meeting",
            "restrictions": "Solo recorte; empatar o subir = NO",
        },
        "resolution_family": "fed_rate_cut_2026",
    },
    {
        "event_id": "fed_rate_sept_2026",
        "event_label": "FED recorte tasa Sept 2026",
        "kalshi_ticker": "FEDRATE-26SEP",
        "limitless_slug": "september-meeting-1779881657549",
        "limitless_group_slug": "fed-rate-cut-by-1779881657530",
        "category": "Fed",
        "expiration": "2026-09-16T00:00:00Z",
        "resolution": {
            "rule": "FOMC recorta la tasa federal funds en la reunión de septiembre 2026",
            "source": "Federal Reserve",
            "threshold": None,
            "currency": "USD",
            "timezone": "America/New_York",
            "exact_wording": "The Federal Open Market Committee lowers the target range for the federal funds rate at the September 16, 2026 meeting",
            "restrictions": "Solo recorte; empatar o subir = NO",
        },
        "resolution_family": "fed_rate_cut_2026",
    },
    {
        "event_id": "fed_rate_oct_2026",
        "event_label": "FED recorte tasa Oct 2026",
        "kalshi_ticker": "FEDRATE-26OCT",
        "limitless_slug": "october-meeting-1779881657552",
        "limitless_group_slug": "fed-rate-cut-by-1779881657530",
        "category": "Fed",
        "expiration": "2026-10-28T00:00:00Z",
        "resolution": {
            "rule": "FOMC recorta la tasa federal funds en la reunión de octubre 2026",
            "source": "Federal Reserve",
            "threshold": None,
            "currency": "USD",
            "timezone": "America/New_York",
            "exact_wording": "The Federal Open Market Committee lowers the target range for the federal funds rate at the October 28, 2026 meeting",
            "restrictions": "Solo recorte; empatar o subir = NO",
        },
        "resolution_family": "fed_rate_cut_2026",
    },
    {
        "event_id": "fed_rate_dec_2026",
        "event_label": "FED recorte tasa Dec 2026",
        "kalshi_ticker": "FEDRATE-26DEC",
        "limitless_slug": "december-meeting-1779881657556",
        "limitless_group_slug": "fed-rate-cut-by-1779881657530",
        "category": "Fed",
        "expiration": "2026-12-09T00:00:00Z",
        "resolution": {
            "rule": "FOMC recorta la tasa federal funds en la reunión de diciembre 2026",
            "source": "Federal Reserve",
            "threshold": None,
            "currency": "USD",
            "timezone": "America/New_York",
            "exact_wording": "The Federal Open Market Committee lowers the target range for the federal funds rate at the December 9, 2026 meeting",
            "restrictions": "Solo recorte; empatar o subir = NO",
        },
        "resolution_family": "fed_rate_cut_2026",
    },
    {
        "event_id": "us_recession_2026",
        "event_label": "Recesión EEUU 2026",
        "kalshi_ticker": "RECESSION-26",
        "limitless_slug": "us-recession-by-end-of-2026-1767804297592",
        "limitless_group_slug": None,
        "category": "Macro",
        "expiration": "2026-12-31T23:59:59Z",
        "resolution": {
            "rule": "La economía de EE.UU. entra en recesión antes del 31 dic 2026 según NBER",
            "source": "NBER (National Bureau of Economic Research)",
            "threshold": None,
            "currency": "USD",
            "timezone": "America/New_York",
            "exact_wording": "The US economy enters a recession as determined by NBER before December 31, 2026",
            "restrictions": "Solo recesión oficial NBER; slowdown técnico no cuenta",
        },
        "resolution_family": "us_recession_2026",
    },
    {
        "event_id": "core_pce_june_2026",
        "event_label": "Core PCE YoY Junio 2026",
        "kalshi_ticker": "PCE-26JUN",
        "limitless_slug": "core-pce-yoy-june-2026-1784042260443",
        "limitless_group_slug": None,
        "category": "Macro",
        "expiration": "2026-07-31T00:00:00Z",
        "resolution": {
            "rule": "El Core PCE YoY de junio 2026 según BEA",
            "source": "Bureau of Economic Analysis (BEA)",
            "threshold": None,
            "currency": "USD",
            "timezone": "America/New_York",
            "exact_wording": "The year-over-year Core PCE price index for June 2026 as reported by BEA",
            "restrictions": "Publicación BEA oficial; revisión posterior no cambia resolución",
        },
        "resolution_family": "core_pce_2026",
    },
    {
        "event_id": "us_gdp_q2_2026",
        "event_label": "US GDP Q2 2026",
        "kalshi_ticker": "GDP-Q2-26",
        "limitless_slug": "us-gdp-growth-in-q2-2026-1777901322288",
        "limitless_group_slug": None,
        "category": "Macro",
        "expiration": "2026-09-30T00:00:00Z",
        "resolution": {
            "rule": "El GDP real de EE.UU. en Q2 2026 según BEA",
            "source": "Bureau of Economic Analysis (BEA)",
            "threshold": None,
            "currency": "USD",
            "timezone": "America/New_York",
            "exact_wording": "US real GDP growth rate for Q2 2026 as reported by BEA advance estimate",
            "restrictions": "Estimación advance; revisiones no cambian resolución",
        },
        "resolution_family": "us_gdp_2026",
    },
    {
        "event_id": "house_2026",
        "event_label": "¿Quién gana la Cámara 2026?",
        "kalshi_ticker": "HOUSE-26",
        "limitless_slug": "which-party-will-win-the-house-in-2026-1769088464314",
        "limitless_group_slug": None,
        "category": "Politics",
        "expiration": "2026-11-03T00:00:00Z",
        "resolution": {
            "rule": "El partido que obtenga mayoría en la Cámara de Representantes en las elecciones de noviembre 2026",
            "source": "Associated Press / CNN",
            "threshold": 218,
            "currency": "USD",
            "timezone": "America/New_York",
            "exact_wording": "Which political party wins a majority of seats in the US House of Representatives in the November 2026 elections",
            "restrictions": "Mayoría = 218+ escaños; empate técnico = resolución pendiente",
        },
        "resolution_family": "house_2026",
    },
    {
        "event_id": "president_2028",
        "event_label": "Presidente EEUU 2028",
        "kalshi_ticker": "PRES-28",
        "limitless_slug": "presidential-election-winner-2028-1769010522121",
        "limitless_group_slug": None,
        "category": "Politics",
        "expiration": "2028-11-07T00:00:00Z",
        "resolution": {
            "rule": "El candidato que gane las elecciones presidenciales de noviembre 2028",
            "source": "Associated Press / CNN",
            "threshold": 270,
            "currency": "USD",
            "timezone": "America/New_York",
            "exact_wording": "The winner of the 2028 US Presidential election",
            "restrictions": "Ganador del Colegio Electoral (270+ votos); resultado oficial tras conteo final",
        },
        "resolution_family": "president_2028",
    },
    {
        "event_id": "dxy_july_2026",
        "event_label": "DXY Dollar Index Julio 2026",
        "kalshi_ticker": "DXY-26JUL",
        "limitless_slug": "which-price-will-dxy-hit-in-july-1782892249118",
        "limitless_group_slug": None,
        "category": "Macro",
        "expiration": "2026-07-31T00:00:00Z",
        "resolution": {
            "rule": "El valor del índice DXY (ICE) al cierre del último día hábil de julio 2026",
            "source": "ICE (Intercontinental Exchange)",
            "threshold": None,
            "currency": "USD",
            "timezone": "America/New_York",
            "exact_wording": "The closing value of the ICE US Dollar Index (DXY) on the last business day of July 2026",
            "restrictions": "Precio de cierre ICE; datos intradía no cuentan",
        },
        "resolution_family": "dxy_2026",
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


def get_pairs_by_resolution_family(family: str) -> list[dict]:
    return [p for p in MARKET_PAIRS if p.get("resolution_family") == family]


def get_catalog_version() -> str:
    return CATALOG_VERSION


def validate_pair(pair: dict) -> list[str]:
    errors = []
    required = ["event_id", "kalshi_ticker", "limitless_slug", "resolution"]
    for field in required:
        if field not in pair:
            errors.append(f"Campo obligatorio ausente: {field}")
    if "resolution" in pair:
        res = pair["resolution"]
        for field in ["rule", "source", "exact_wording"]:
            if field not in res:
                errors.append(f"resolution.{field} ausente")
    return errors
