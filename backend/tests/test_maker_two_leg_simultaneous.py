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
        symbol="limitless_crypto_btc-up-or-down-5-min-9999",
        price=0.50,
        bid=0.015,
        ask=0.065,  # YES bid = 0.015, ask = 0.065 -> NO bid = 1.0 - 0.065 = 0.935
        chart_price="BTC 5m test",
    )
    event.bid_size = 500.0
    event.ask_size = 500.0
    event.market_volume = 1500.0
    event.market_slug = "btc-up-or-down-5-min-9999"
    event.expiration_timestamp = 2000000000.0  # Future expiration (far from TTL limit)

    sig1 = strategy.on_price_update(event)

    assert sig1 is not None
    assert "_YES" in sig1.symbol
    assert sig1.side == "BUY"
    assert sig1.order_type == "GTC"
    assert sig1.price == 0.015

    # Validar que la Pata 2 quedó en _pending_signals
    assert len(strategy._pending_signals) == 1
    sig2 = strategy._pending_signals[0]
    assert "_NO" in sig2.symbol
    assert sig2.side == "BUY"
    assert sig2.order_type == "GTC"
    assert sig2.price == 0.935

    # Costo total combinado: 0.015 + 0.935 = 0.950 (5.0% de spread)
    assert round(sig1.price + sig2.price, 3) == 0.950


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
        symbol="limitless_crypto_btc-up-or-down-5-min-9999",
        price=0.50,
        bid=0.48,
        ask=0.52,
        chart_price="BTC 5m test",
    )
    event.bid_size = 500.0
    event.ask_size = 500.0
    event.market_volume = 1500.0
    event.market_slug = "btc-up-or-down-5-min-9999"
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
    assert "_YES" in sig.symbol
    assert pair.status == "SCRATCHED"
