import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

from src.events import PriceUpdateEvent, SignalEvent
from src.strategy.maker_two_leg_strategy import MakerTwoLegStrategy
from src.engine.maker_taker_coordinator import (
    MakerTakerCoordinator,
    RestingMakerOrder,
    MakerPair,
)


def test_maker_two_leg_emits_both_signals_simultaneously():
    """Valida que la estrategia Maker emite Pata 1 y encola Pata 2 con tipo GTC."""
    mock_db = MagicMock()
    strategy = MakerTwoLegStrategy(
        db=mock_db,
        worker_id="worker_6",
        symbol="CRYPTO_MAKER",
        min_edge_pct=0.02,
        position_size_usd=1.0,
        observation_only=False,
        sequential_mode=False,
    )

    event = PriceUpdateEvent(
        symbol="limitless_crypto_btc-up-or-down-15-min-9999",
        price=0.50,
        bid=0.015,
        ask=0.065,  # YES bid = 0.015, ask = 0.065 -> NO bid = 1.0 - 0.065 = 0.935
        chart_price="BTC 15m test",
    )
    event.bid_size = 500.0
    event.ask_size = 500.0
    event.market_volume = 1500.0
    event.market_slug = "btc-up-or-down-15-min-9999"
    event.expiration_timestamp = 2000000000.0  # Future expiration (far from TTL limit)

    sig1 = strategy.on_price_update(event)

    assert sig1 is not None
    assert "_YES" in sig1.symbol
    assert sig1.side == "BUY"
    assert sig1.order_type == "GTC"
    assert sig1.price == 0.015

    # Validar que la Pata 2 quedo en _pending_signals
    assert len(strategy._pending_signals) == 1
    sig2 = strategy._pending_signals[0]
    assert "_NO" in sig2.symbol
    assert sig2.side == "BUY"
    assert sig2.order_type == "GTC"
    assert sig2.price == 0.935

    # Costo total combinado: 0.015 + 0.935 = 0.950 (5.0% de spread)
    assert round(sig1.price + sig2.price, 3) == 0.950


def test_maker_two_leg_strictly_rejects_5min_markets():
    """Valida que los mercados de 5 minutos son estrictamente rechazados."""
    mock_db = MagicMock()
    strategy = MakerTwoLegStrategy(
        db=mock_db,
        worker_id="worker_6",
        symbol="CRYPTO_MAKER",
    )

    for slug in ["btc-up-or-down-5-min-12345", "eth-up-or-down-5min-999"]:
        event = PriceUpdateEvent(
            symbol=f"limitless_crypto_{slug}",
            price=0.50,
            bid=0.48,
            ask=0.52,
        )
        event.bid_size = 500.0
        event.ask_size = 500.0
        event.market_slug = slug
        sig = strategy.on_price_update(event)
        assert sig is None
        assert strategy._diag.get("5min_filtered", 0) > 0


def test_maker_two_leg_avellaneda_stoikov_inventory_skew():
    """Valida que el modelo Avellaneda-Stoikov sesga las cotizaciones segun el inventario q."""
    mock_db = MagicMock()
    strategy = MakerTwoLegStrategy(
        db=mock_db,
        worker_id="worker_6",
        symbol="CRYPTO_MAKER",
        min_edge_pct=0.02,
        position_size_usd=1.0,
        observation_only=False,
        sequential_mode=False,
        inventory_gamma=0.02,
        inventory_soft_cap=2.0,
    )

    slug = "btc-up-or-down-15-min-as-test"
    # Estado inicial q = 0
    assert strategy.get_net_inventory(slug) == 0.0

    # Simular que tenemos 1 contrato YES de inventario (q = +1.0)
    strategy.update_inventory(slug, "yes", 1.0)
    assert strategy.get_net_inventory(slug) == 1.0

    event = PriceUpdateEvent(
        symbol=f"limitless_crypto_{slug}",
        price=0.50,
        bid=0.47,
        ask=0.53,
    )
    event.bid_size = 500.0
    event.ask_size = 500.0
    event.market_volume = 1500.0
    event.market_slug = slug
    event.expiration_timestamp = 2000000000.0

    sig_yes = strategy.on_price_update(event)
    assert sig_yes is not None
    # Con q = +1.0, FV = 0.50, r = 0.50 - 0.02*1 = 0.48
    # YES bid se sesga a la baja: r - half_spread = 0.48 - 0.015 = 0.465
    assert sig_yes.price < 0.47  # Menor que el bid original porque estamos sobre-cargados de YES

    # NO bid en pending_signals se sesga al alza para atraer contraparte:
    sig_no = strategy._pending_signals[0]
    # (1 - r) - half_spread = (1 - 0.48) - 0.015 = 0.505 > (1 - 0.53) = 0.47
    assert sig_no.price > 0.47

    # Simular que alcanzamos el soft cap (q = +2.0): solo cotiza REDUCE_ONLY (solo NO)
    strategy._pending_signals.clear()
    strategy._last_signal_time.clear()
    strategy.update_inventory(slug, "yes", 1.0)  # q = 2.0
    assert strategy.get_net_inventory(slug) == 2.0

    sig_reduce = strategy.on_price_update(event)
    assert sig_reduce is not None
    assert "_NO" in sig_reduce.symbol  # Solo cotiza NO para reducir el exceso de YES
    assert len(strategy._pending_signals) == 0  # No cotiza YES en absoluto


def test_maker_two_leg_sequential_mode():
    """Valida que en modo secuencial solo emite 1 pata maker y no encola pata 2."""
    mock_db = MagicMock()
    strategy = MakerTwoLegStrategy(
        db=mock_db,
        worker_id="worker_6",
        symbol="CRYPTO_MAKER",
        min_edge_pct=0.02,
        position_size_usd=1.0,
        observation_only=False,
        sequential_mode=True,
    )

    event = PriceUpdateEvent(
        symbol="limitless_crypto_btc-up-or-down-15-min-9999",
        price=0.50,
        bid=0.48,
        ask=0.52,
        chart_price="BTC 15m test",
    )
    event.bid_size = 500.0
    event.ask_size = 500.0
    event.market_volume = 1500.0
    event.market_slug = "btc-up-or-down-15-min-9999"
    event.expiration_timestamp = 2000000000.0

    sig = strategy.on_price_update(event)
    assert sig is not None
    assert sig.order_type == "GTC"
    assert len(strategy._pending_signals) == 0  # Cero órdenes pasivas descalzadas


def test_coordinator_handles_dual_resting_and_adverse_cancellation():
    """Valida que el coordinador gestiona el par dual y cancela ambas si hay salto de spot."""
    mock_db = MagicMock()
    coord = MakerTakerCoordinator(db=mock_db)

    slug = "btc-up-or-down-5-min-jump-test"
    ord_yes = RestingMakerOrder(
        order_id="ord_yes_1",
        worker_id="worker_6",
        market_slug=slug,
        token_id="tok_yes",
        side="BUY",
        price=0.015,
        spend_amount=1.0,
        shares=66.66,
        leg_name="YES",
        hedge_token_id="tok_no",
        hedge_leg_name="NO",
        hedge_max_price=0.965,
        target_asset="BTC",
    )
    ord_no = RestingMakerOrder(
        order_id="ord_no_1",
        worker_id="worker_6",
        market_slug=slug,
        token_id="tok_no",
        side="BUY",
        price=0.935,
        spend_amount=1.0,
        shares=1.069,
        leg_name="NO",
        hedge_token_id="tok_yes",
        hedge_leg_name="YES",
        hedge_max_price=0.045,
        target_asset="BTC",
    )
    coord.register_order(ord_yes)
    coord.register_order(ord_no)
    pair = coord.register_pair(slug, "ord_yes_1", "ord_no_1", 0.950, "worker_6")

    # Ambas órdenes están descansando
    actives = coord.get_active_orders("worker_6")
    assert len(actives) == 2

    # Simular salto de 15 bps en Binance spot BTC
    with patch("src.strategy.lead_lag_arbitrage.BinanceTracker.detect_jump", return_value=(True, 15.2)):
        jump1, r1 = coord.check_adverse_selection("ord_yes_1")
        jump2, r2 = coord.check_adverse_selection("ord_no_1")
        assert jump1 is True
        assert jump2 is True

        # Cancelar por toxic flow
        coord.mark_cancelled("ord_yes_1", r1)
        coord.mark_cancelled("ord_no_1", r2)

    assert ord_yes.status == "CANCELLED"
    assert ord_no.status == "CANCELLED"
    assert len(coord.get_active_orders("worker_6")) == 0


def test_coordinator_handles_successful_dual_fill():
    """Valida que cuando ambas órdenes Maker se llenan, el par pasa a BOTH_FILLED."""
    mock_db = MagicMock()
    coord = MakerTakerCoordinator(db=mock_db)

    slug = "eth-up-or-down-5-min-success"
    ord_yes = RestingMakerOrder(
        order_id="ord_yes_ok",
        worker_id="worker_6",
        market_slug=slug,
        token_id="tok_yes",
        side="BUY",
        price=0.40,
        spend_amount=1.0,
        shares=2.5,
        leg_name="YES",
        hedge_token_id="tok_no",
        hedge_leg_name="NO",
        hedge_max_price=0.58,
    )
    ord_no = RestingMakerOrder(
        order_id="ord_no_ok",
        worker_id="worker_6",
        market_slug=slug,
        token_id="tok_no",
        side="BUY",
        price=0.55,
        spend_amount=1.0,
        shares=1.818,
        leg_name="NO",
        hedge_token_id="tok_yes",
        hedge_leg_name="YES",
        hedge_max_price=0.43,
    )
    coord.register_order(ord_yes)
    coord.register_order(ord_no)
    pair = coord.register_pair(slug, "ord_yes_ok", "ord_no_ok", 0.950, "worker_6")

    # Ambas se llenan
    coord.mark_filled("ord_yes_ok")
    coord.mark_filled("ord_no_ok")

    status, sig, cancel_id = coord.evaluate_pair(slug, current_yes_ask=0.45, current_no_ask=0.60)
    assert status == "BOTH_FILLED"
    assert sig is None
    assert cancel_id is None
    assert pair.status == "BOTH_FILLED"


def test_coordinator_triggers_fok_hedge_when_profitable():
    """Valida que si YES se llena y NO sigue rentable, dispara FOK BUY NO y cancela orden NO resting."""
    mock_db = MagicMock()
    coord = MakerTakerCoordinator(db=mock_db)

    slug = "btc-up-or-down-5-min-hedge-test"
    ord_yes = RestingMakerOrder(
        order_id="ord_yes_h",
        worker_id="worker_6",
        market_slug=slug,
        token_id="tok_yes",
        side="BUY",
        price=0.42,
        spend_amount=1.0,
        shares=2.38,
        leg_name="YES",
        hedge_token_id="tok_no",
        hedge_leg_name="NO",
        hedge_max_price=0.56,
    )
    ord_no = RestingMakerOrder(
        order_id="ord_no_h",
        worker_id="worker_6",
        market_slug=slug,
        token_id="tok_no",
        side="BUY",
        price=0.52,
        spend_amount=1.0,
        shares=1.92,
        leg_name="NO",
        hedge_token_id="tok_yes",
        hedge_leg_name="YES",
        hedge_max_price=0.46,
    )
    coord.register_order(ord_yes)
    coord.register_order(ord_no)
    pair = coord.register_pair(slug, "ord_yes_h", "ord_no_h", 0.940, "worker_6")

    # Solo YES se llena on-chain
    coord.mark_filled("ord_yes_h")

    # Ask de NO en el mercado es 0.54 (total cost = 0.42 + 0.54 = 0.96 <= 0.985)
    status, sig, cancel_id = coord.evaluate_pair(
        slug,
        current_yes_ask=0.45,
        current_no_ask=0.54,
        current_yes_bid=0.41,
        current_no_bid=0.51,
        max_unhedged_wait_s=0.0,
        max_total_cost=0.985,
    )

    assert status == "TRIGGER_FOK_NO"
    assert cancel_id == "ord_no_h"
    assert sig is not None
    assert sig.side == "BUY"
    assert sig.order_type == "FOK"
    assert sig.price == 0.54
    assert "_NO" in sig.symbol
    assert pair.status == "HEDGED_FOK"


def test_coordinator_triggers_scratch_unwind_on_toxic_flow():
    """Valida que si YES se llena pero NO se disparó > 1.00 (toxic flow), vende YES al bid inmediatamente."""
    mock_db = MagicMock()
    coord = MakerTakerCoordinator(db=mock_db)

    slug = "btc-up-or-down-5-min-scratch-test"
    ord_yes = RestingMakerOrder(
        order_id="ord_yes_s",
        worker_id="worker_6",
        market_slug=slug,
        token_id="tok_yes",
        side="BUY",
        price=0.906,
        spend_amount=1.0,
        shares=1.103,
        leg_name="YES",
        hedge_token_id="tok_no",
        hedge_leg_name="NO",
        hedge_max_price=0.08,
    )
    ord_no = RestingMakerOrder(
        order_id="ord_no_s",
        worker_id="worker_6",
        market_slug=slug,
        token_id="tok_no",
        side="BUY",
        price=0.036,
        spend_amount=1.0,
        shares=27.7,
        leg_name="NO",
        hedge_token_id="tok_yes",
        hedge_leg_name="YES",
        hedge_max_price=0.95,
    )
    coord.register_order(ord_yes)
    coord.register_order(ord_no)
    pair = coord.register_pair(slug, "ord_yes_s", "ord_no_s", 0.942, "worker_6")

    # YES se llena on-chain
    coord.mark_filled("ord_yes_s")

    # Ask de NO subió a 0.99 (mercado colapsando, total = 0.906 + 0.99 = 1.896 > 0.985)
    status, sig, cancel_id = coord.evaluate_pair(
        slug,
        current_yes_ask=0.91,
        current_no_ask=0.99,
        current_yes_bid=0.895,
        current_no_bid=0.01,
        max_unhedged_wait_s=0.0,
        max_total_cost=0.985,
    )

    assert status == "TRIGGER_SCRATCH_YES"
    assert cancel_id == "ord_no_s"
    assert sig is not None
    assert sig.side == "SELL"
    assert sig.order_type == "FOK"
    assert sig.price == 0.895


def test_maker_two_leg_blocks_different_market_when_one_is_active():
    """Valida que si hay una orden activa en BTC, la estrategia ignora ticks de ETH para no cruzar dos mercados."""
    from src.engine.maker_taker_coordinator import maker_taker_coordinator, RestingMakerOrder

    mock_db = MagicMock()
    mock_db.get_open_positions.return_value = []
    strategy = MakerTwoLegStrategy(
        db=mock_db,
        worker_id="worker_6",
        symbol="CRYPTO_MAKER",
        min_edge_pct=0.02,
        position_size_usd=1.0,
        observation_only=False,
    )

    btc_slug = "btc-up-or-down-15-min-9999"
    eth_slug = "eth-up-or-down-15-min-9999"

    # Registrar orden activa en BTC
    btc_ord = RestingMakerOrder(
        order_id="btc_ord_1",
        worker_id="worker_6",
        market_slug=btc_slug,
        token_id="tok_btc_yes",
        side="BUY",
        price=0.48,
        spend_amount=1.0,
        shares=2.08,
        leg_name="YES",
        hedge_token_id="tok_btc_no",
        hedge_leg_name="NO",
        hedge_max_price=0.50,
    )
    maker_taker_coordinator.register_order(btc_ord)

    # Llega un tick de ETH (con buen spread y volumen)
    eth_event = PriceUpdateEvent(
        symbol=f"limitless_crypto_{eth_slug}",
        price=0.50,
        bid=0.48,
        ask=0.52,
    )
    eth_event.bid_size = 500.0
    eth_event.ask_size = 500.0
    eth_event.market_volume = 1500.0
    eth_event.market_slug = eth_slug
    eth_event.expiration_timestamp = 2000000000.0

    sig = strategy.on_price_update(eth_event)

    # DEBE SER RECHAZADO: hay orden activa en BTC, no se puede tocar ETH
    assert sig is None
    assert strategy._diag.get("other_market_active", 0) > 0

    # Limpiar orden para no ensuciar otros tests
    maker_taker_coordinator.mark_cancelled("btc_ord_1", "test_cleanup")


def test_maker_micro_position_sizing_defaults(monkeypatch):
    """Valida que el dimensionamiento por defecto sea micro-lotes ($0.20 a $0.50, default $0.35)."""
    for k in ["MAKER_LEG_MIN_USD", "CRYPTO_LEG_MIN_USD", "MAKER_LEG_MAX_USD", "CRYPTO_LEG_MAX_USD", "MAKER_POSITION_SIZE_USD", "CRYPTO_MAKER_POSITION_SIZE_USD"]:
        monkeypatch.delenv(k, raising=False)
    mock_db = MagicMock()
    strategy = MakerTwoLegStrategy(
        db=mock_db,
        worker_id="worker_6",
        symbol="CRYPTO_MAKER",
    )
    assert strategy.leg_size_min_usd == 0.20
    assert strategy.leg_size_max_usd == 0.50
    assert strategy.position_size_usd == 0.35


@pytest.mark.asyncio
async def test_auto_redeem_clob_portfolio_claims_winning_contract():
    """Valida que auto_redeem_clob_portfolio escanea la cartera y ejecuta redeem para contratos ganadores."""
    from src.engine.redeem_executor import RedeemExecutor, RedeemResult

    mock_db = MagicMock()
    executor = RedeemExecutor(db=mock_db, worker_id="worker_6")

    # Mock client and CLOB data
    fake_market = {
        "slug": "btc-up-or-down-15-min-9999",
        "status": "RESOLVED",
        "conditionId": "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        "winningOutcomeIndex": 0,  # YES won
    }
    fake_item = {
        "market": fake_market,
        "tokensBalance": {"yes": "1000000", "no": "0"},  # 1.0 YES held
    }

    mock_client = AsyncMock()
    mock_client.portfolio.get_clob_positions = AsyncMock(return_value=[fake_item])

    with patch.dict("os.environ", {
        "LIMITLESS_API_KEY": "fake_key",
        "LIMITLESS_API_SECRET": "fake_sec",
        "LIMITLESS_PRIVATE_KEY": "fake_priv",
    }), patch("limitless_sdk.Client") as MockClientClass, \
       patch.object(executor, "redeem", new_callable=AsyncMock) as mock_redeem:

        mock_redeem.return_value = RedeemResult(
            success=True,
            market_slug="btc-up-or-down-15-min-9999",
            condition_id="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            winning_outcome="YES",
            shares_redeemed=1.0,
            usdc_received=1.0,
            tx_hash="0xtesthash123",
        )

        MockClientClass.return_value.__aenter__.return_value = mock_client

        results = await executor.auto_redeem_clob_portfolio()

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].winning_outcome == "YES"
        mock_redeem.assert_awaited_once_with(
            condition_id="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            winning_outcome="YES",
            shares=1.0,
            is_negrisk=False,
        )
