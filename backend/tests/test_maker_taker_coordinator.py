import pytest
import time
from unittest.mock import patch, MagicMock

from src.engine.maker_taker_coordinator import (
    MakerTakerCoordinator,
    RestingMakerOrder,
)
from src.events import SignalEvent


class TestMakerTakerCoordinator:

    def setup_method(self):
        self.mock_db = MagicMock()
        self.coordinator = MakerTakerCoordinator(db=self.mock_db)

    def test_register_and_get_order(self):
        order = RestingMakerOrder(
            order_id="test_ord_123",
            worker_id="worker_6",
            market_slug="btc-up-or-down-5-min-12345",
            token_id="tok_yes_1",
            side="BUY",
            price=0.35,
            spend_amount=1.0,
            shares=2.857,
            leg_name="YES",
            hedge_token_id="tok_no_1",
            hedge_leg_name="NO",
            hedge_max_price=0.63,
            max_total_cost=0.98,
            target_asset="BTC",
        )
        self.coordinator.register_order(order)

        retrieved = self.coordinator.get_resting_order("test_ord_123")
        assert retrieved is not None
        assert retrieved.order_id == "test_ord_123"
        assert retrieved.status == "RESTING"

        actives = self.coordinator.get_active_orders("worker_6")
        assert len(actives) == 1
        assert actives[0].order_id == "test_ord_123"

    def test_spread_viability(self):
        order = RestingMakerOrder(
            order_id="test_spread_1",
            worker_id="worker_6",
            market_slug="btc-up-or-down-5-min-12345",
            token_id="tok_yes_1",
            side="BUY",
            price=0.35,
            spend_amount=1.0,
            shares=2.857,
            leg_name="YES",
            hedge_token_id="tok_no_1",
            hedge_leg_name="NO",
            hedge_max_price=0.63,
            max_total_cost=0.98,
        )
        self.coordinator.register_order(order)

        # Viable: 0.35 + 0.60 = 0.95 <= 0.98
        viable, reason = self.coordinator.check_spread_viability("test_spread_1", current_hedge_ask=0.60)
        assert viable is True
        assert "viable" in reason

        # Not viable: 0.35 + 0.64 = 0.99 > 0.98
        viable, reason = self.coordinator.check_spread_viability("test_spread_1", current_hedge_ask=0.64)
        assert viable is False
        assert "spread_unfavorable" in reason

    def test_adverse_selection_check(self):
        order = RestingMakerOrder(
            order_id="test_adv_1",
            worker_id="worker_6",
            market_slug="btc-up-or-down-5-min-12345",
            token_id="tok_yes_1",
            side="BUY",
            price=0.35,
            spend_amount=1.0,
            shares=2.857,
            leg_name="YES",
            hedge_token_id="tok_no_1",
            hedge_leg_name="NO",
            hedge_max_price=0.63,
            target_asset="BTC",
        )
        self.coordinator.register_order(order)

        # Simular sin salto en Binance
        with patch("src.strategy.lead_lag_arbitrage.BinanceTracker.detect_jump", return_value=(False, 0.0)):
            is_jump, reason = self.coordinator.check_adverse_selection("test_adv_1")
            assert is_jump is False
            assert reason == "ok"

        # Simular salto tóxico de 18 bps
        with patch("src.strategy.lead_lag_arbitrage.BinanceTracker.detect_jump", return_value=(True, 18.5)):
            is_jump, reason = self.coordinator.check_adverse_selection("test_adv_1")
            assert is_jump is True
            assert "adverse_selection_jump" in reason
            assert "18.5bps" in reason

    def test_expiration_check(self):
        now = 1000.0
        order = RestingMakerOrder(
            order_id="test_exp_1",
            worker_id="worker_6",
            market_slug="btc-up-or-down-5-min-12345",
            token_id="tok_yes_1",
            side="BUY",
            price=0.35,
            spend_amount=1.0,
            shares=2.857,
            leg_name="YES",
            hedge_token_id="tok_no_1",
            hedge_leg_name="NO",
            hedge_max_price=0.63,
            expires_at=1050.0,  # Faltan 50s
        )
        self.coordinator.register_order(order)

        # Con buffer de 60s, 50s restantes debe activar cancelación
        is_expiring, reason = self.coordinator.check_expiration("test_exp_1", now=now, min_buffer_seconds=60.0)
        assert is_expiring is True
        assert "near_expiration" in reason

        # Si faltan 120s, no debe expirar
        order.expires_at = 1120.0
        is_expiring, reason = self.coordinator.check_expiration("test_exp_1", now=now, min_buffer_seconds=60.0)
        assert is_expiring is False

    def test_build_hedge_signal_and_mark_hedged(self):
        order = RestingMakerOrder(
            order_id="test_hedge_1",
            worker_id="worker_6",
            market_slug="btc-up-or-down-5-min-12345",
            token_id="tok_yes_1",
            side="BUY",
            price=0.35,
            spend_amount=1.0,
            shares=2.8571,
            leg_name="YES",
            hedge_token_id="tok_no_1",
            hedge_leg_name="NO",
            hedge_max_price=0.63,
        )
        self.coordinator.register_order(order)

        # Simular fill de pata 1
        self.coordinator.mark_filled("test_hedge_1", filled_price=0.35, filled_qty=2.8571)
        assert order.status == "FILLED"

        # Construir señal de hedge para Pata 2
        hedge_sig = self.coordinator.build_hedge_signal(order, current_hedge_ask=0.61)
        assert isinstance(hedge_sig, SignalEvent)
        assert hedge_sig.symbol == "limitless_crypto_btc-up-or-down-5-min-12345_NO"
        assert hedge_sig.side == "BUY"
        assert hedge_sig.price == 0.61
        assert hedge_sig.order_type == "FOK"
        # 2.8571 shares * 0.61 = 1.7428 USD
        assert hedge_sig.position_size_usd == round(2.8571 * 0.61, 4)

        # Completar hedge
        self.coordinator.mark_hedged("test_hedge_1", hedge_order_id="hedge_ord_999", hedge_price=0.61)
        assert order.status == "HEDGED"
        assert order.hedge_order_id == "hedge_ord_999"

    def test_ws_order_event(self):
        order = RestingMakerOrder(
            order_id="ws_ord_555",
            worker_id="worker_6",
            market_slug="eth-up-or-down-5-min-999",
            token_id="tok_yes_2",
            side="BUY",
            price=0.40,
            spend_amount=1.0,
            shares=2.5,
            leg_name="YES",
            hedge_token_id="tok_no_2",
            hedge_leg_name="NO",
            hedge_max_price=0.58,
        )
        self.coordinator.register_order(order)

        # Evento MINED (Settlement)
        ws_data_mined = {
            "orderId": "ws_ord_555",
            "source": "SETTLEMENT",
            "type": "MINED",
        }
        res = self.coordinator.on_ws_order_event(ws_data_mined)
        assert res == ("ws_ord_555", "FILLED")
        assert order.status == "FILLED"

        # Evento CANCELLATION en otra orden
        order2 = RestingMakerOrder(
            order_id="ws_ord_666",
            worker_id="worker_6",
            market_slug="eth-up-or-down-5-min-999",
            token_id="tok_yes_2",
            side="BUY",
            price=0.40,
            spend_amount=1.0,
            shares=2.5,
            leg_name="YES",
            hedge_token_id="tok_no_2",
            hedge_leg_name="NO",
            hedge_max_price=0.58,
        )
        self.coordinator.register_order(order2)

        ws_data_cancel = {
            "orderId": "ws_ord_666",
            "source": "OME",
            "type": "CANCELLATION",
        }
        res2 = self.coordinator.on_ws_order_event(ws_data_cancel)
        assert res2 == ("ws_ord_666", "CANCELLED")
        assert order2.status == "CANCELLED"

    def test_maker_pair_evaluation_and_fok_guardrail(self):
        slug = "btc-up-or-down-5-min-9999"
        ord_yes = RestingMakerOrder(
            order_id="ord_pair_yes",
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
        )
        ord_no = RestingMakerOrder(
            order_id="ord_pair_no",
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
        )
        self.coordinator.register_order(ord_yes)
        self.coordinator.register_order(ord_no)

        pair = self.coordinator.register_pair(
            market_slug=slug,
            yes_order_id="ord_pair_yes",
            no_order_id="ord_pair_no",
            target_total_cost=0.950,
            worker_id="worker_6",
        )
        assert pair is not None

        # 1. Al inicio, ambas están RESTING
        status, sig = self.coordinator.evaluate_pair(slug, current_yes_ask=0.05, current_no_ask=0.96)
        assert status == "BOTH_RESTING"
        assert sig is None

        # 2. YES se llena a t=100. NO sigue resting.
        self.coordinator.mark_filled("ord_pair_yes")
        status, sig = self.coordinator.evaluate_pair(
            slug, current_yes_ask=0.05, current_no_ask=0.96, max_unhedged_wait_s=15.0, now=105.0
        )
        # Han pasado 5s (< 15s) -> espera tranquila
        assert status == "ONE_FILLED_AWAITING"
        assert sig is None

        # 3. Pasan 20s (t=125) sin que NO se llene -> SE DISPARA EL GUARDRAIL FOK
        status, sig = self.coordinator.evaluate_pair(
            slug, current_yes_ask=0.05, current_no_ask=0.965, max_unhedged_wait_s=15.0, now=125.0
        )
        assert status == "TRIGGER_FOK_NO"
        assert sig is not None
        assert sig.side == "BUY"
        assert sig.order_type == "FOK"
        assert sig.price == 0.965
        assert pair.status == "HEDGED_FOK"
