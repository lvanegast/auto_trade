"""
auto_trade — Paquete principal del bot de trading event-driven.

Módulos:
    api         — Rutas FastAPI y montaje del frontend estático
    engine      — Motor de trading (TradingEngine) con loop de eventos asíncrono
    database    — Capa de acceso a datos PostgreSQL (DatabaseManager)
    events      — Clases de eventos: PriceUpdateEvent, SignalEvent, OrderEvent
    feeders     — Fuentes de datos de mercado (Mock, OANDA, IG Group)
    strategy    — Estrategias de trading algorítmico (EMA+RSI, extensibles)
"""
