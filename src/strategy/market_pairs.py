"""
Configuración de pares de mercados cross-platform para arbitraje Kalshi ↔ Polymarket.
Cada par define el mismo evento real listado en ambas plataformas con IDs diferentes.

Los precios en ambos platforms son binarios [0.0, 1.0] representando probabilidad YES.
"""

# Cada par tiene:
#   event_id:        identificador lógico del evento
#   event_label:     nombre legible para UI
#   kalshi_ticker:   ticker del contrato YES en Kalshi
#   polymarket_token_id: token ID del contrato YES en Polymarket
#   category:        agrupación para UI (Fed, Macro, Crypto, etc.)

MARKET_PAIRS = [
    {
        "event_id": "fed_rate_july_2026",
        "event_label": "FED recorte tasa Julio 2026",
        "kalshi_ticker": "FEDRATE-26JUL",
        "polymarket_token_id": "47264103806485835404991710683382382893450389733731657763409611371684548493438",
        "category": "Fed",
    },
    {
        "event_id": "fed_rate_sept_2026",
        "event_label": "FED recorte tasa Sept 2026",
        "kalshi_ticker": "FEDRATE-26SEP",
        "polymarket_token_id": "54528424949887017954542079473467803508960862404441013773244661393552552196707",
        "category": "Fed",
    },
    {
        "event_id": "fed_no_cut_july_2026",
        "event_label": "FED sin recorte Julio 2026",
        "kalshi_ticker": "FEDRATE-26JUL-N",
        "polymarket_token_id": "35489598453220098404991710683382382893450389733731657763409611371684548493438",
        "category": "Fed",
    },
    {
        "event_id": "inflation_below_26",
        "event_label": "Inflación EEUU < 2.6%",
        "kalshi_ticker": "INFLATION-26",
        "polymarket_token_id": None,  # Polymarket no tiene este exacto; placeholder para matching futuro
        "category": "Macro",
    },
    {
        "event_id": "us_recession_q3_2026",
        "event_label": "Recesión EEUU Q3 2026",
        "kalshi_ticker": "RECESSION-Q3-26",
        "polymarket_token_id": "13103112820996036653459332967500408557040875298442055053142221614689276932366",
        "category": "Macro",
    },
    {
        "event_id": "btc_above_150k",
        "event_label": "BTC > $150,000 en 2026",
        "kalshi_ticker": "BTC-26",
        "polymarket_token_id": "21742617192661590740925574347715096531393664724810793796541603527267389823616",
        "category": "Crypto",
    },
]


def get_pair_by_kalshi_ticker(ticker: str) -> dict | None:
    """Busca un par por ticker de Kalshi."""
    for pair in MARKET_PAIRS:
        if pair["kalshi_ticker"] == ticker:
            return pair
    return None


def get_pair_by_polymarket_token(token_id: str) -> dict | None:
    """Busca un par por token ID de Polymarket."""
    for pair in MARKET_PAIRS:
        if pair["polymarket_token_id"] == token_id:
            return pair
    return None


def get_pair_by_event_id(event_id: str) -> dict | None:
    """Busca un par por event_id lógico."""
    for pair in MARKET_PAIRS:
        if pair["event_id"] == event_id:
            return pair
    return None


def get_active_pairs() -> list[dict]:
    """Retorna solo pares que tienen ambos platforms configurados."""
    return [p for p in MARKET_PAIRS if p["polymarket_token_id"] is not None]
