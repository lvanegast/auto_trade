"""
Unit tests for Combinatorial Arbitrage (Dual Simplex LP) and Adverse Selection Protection.
"""

import time
from src.strategy.combinatorial_arb import CoveringLPSolver, CombinatorialArbitrage
from src.strategy.lead_lag_arbitrage import BinanceTracker


def test_lp_solver_simple_2way():
    """Test standard 2-way binary market via LP covering."""
    # 2 outcomes, both paying in their own state
    matrix = [
        [1.0, 0.0],
        [0.0, 1.0],
    ]
    # Total cost = 0.45 + 0.48 = 0.93 < 1.00
    costs = [0.45, 0.48]
    x_star, optimal_cost, is_optimal, status = CoveringLPSolver.solve(costs, matrix)
    assert is_optimal is True
    assert round(optimal_cost, 4) == 0.93
    assert round(x_star[0], 2) == 1.0
    assert round(x_star[1], 2) == 1.0


def test_lp_solver_tennis_bo3():
    """Test 4-state Tennis Best-of-3 model."""
    contracts = [
        {"name": "P1 YES", "slug": "t-1", "type": "P1_WIN", "side": "YES", "cost": 0.55, "depth": 100},
        {"name": "P2 YES", "slug": "t-1", "type": "P2_WIN", "side": "YES", "cost": 0.52, "depth": 100},
        {"name": "3+ Sets YES", "slug": "t-2", "type": "3_SETS", "side": "YES", "cost": 0.42, "depth": 100},
        {"name": "3+ Sets NO", "slug": "t-2", "type": "3_SETS", "side": "NO", "cost": 0.50, "depth": 100},
    ]
    states, matrix = CombinatorialArbitrage.build_tennis_bo3_model(contracts)
    assert len(states) == 4
    costs = [c["cost"] for c in contracts]

    x_star, optimal_cost, is_optimal, status = CoveringLPSolver.solve(costs, matrix)
    assert is_optimal is True
    # In this price set: 3+ sets YES (0.42) + 3+ sets NO (0.50) = 0.92 < 1.00
    assert round(optimal_cost, 4) == 0.92
    assert x_star[2] == 1.0
    assert x_star[3] == 1.0


def test_lp_solver_esports_bo3():
    """Test 6-state Esports Best-of-3 model."""
    contracts = [
        {"name": "T1 Match", "slug": "e-1", "type": "T1_MATCH", "side": "YES", "cost": 0.52, "depth": 100},
        {"name": "T2 Match", "slug": "e-1", "type": "T2_MATCH", "side": "YES", "cost": 0.51, "depth": 100},
        {"name": "T1 Map 1", "slug": "e-2", "type": "T1_MAP1", "side": "YES", "cost": 0.53, "depth": 100},
        {"name": "T2 Map 1", "slug": "e-2", "type": "T2_MAP1", "side": "YES", "cost": 0.50, "depth": 100},
        {"name": "T1 Map 2", "slug": "e-3", "type": "T1_MAP2", "side": "YES", "cost": 0.44, "depth": 100},
        {"name": "T2 Map 2", "slug": "e-3", "type": "T2_MAP2", "side": "YES", "cost": 0.49, "depth": 100},
    ]
    states, matrix = CombinatorialArbitrage.build_esports_bo3_model(contracts)
    assert len(states) == 6
    costs = [c["cost"] for c in contracts]

    x_star, optimal_cost, is_optimal, status = CoveringLPSolver.solve(costs, matrix)
    assert is_optimal is True
    # Map 2 arb: 0.44 + 0.49 = 0.93
    assert round(optimal_cost, 4) == 0.93
    assert x_star[4] == 1.0
    assert x_star[5] == 1.0


def test_cluster_markets_by_match():
    """Test grouping independent sub-markets into match clusters."""
    markets = [
        {"title": "Aryna Sabalenka vs Linda Noskova", "slug": "sabalenka-vs-noskova-1"},
        {"title": "Aryna Sabalenka vs Linda Noskova: 3 or more total sets?", "slug": "sabalenka-vs-noskova-sets"},
        {"title": "G2 vs Astralis", "slug": "g2-astralis-match"},
        {"title": "G2 vs Astralis: Map 1 Winner", "slug": "g2-astralis-m1"},
        {"title": "G2 vs Astralis: Map 2 Winner", "slug": "g2-astralis-m2"},
    ]
    clusters = CombinatorialArbitrage.cluster_markets_by_match(markets)
    assert "aryna-sabalenka-vs-linda-noskova" in clusters
    assert len(clusters["aryna-sabalenka-vs-linda-noskova"]) == 2
    assert "astralis-vs-g2" in clusters
    assert len(clusters["astralis-vs-g2"]) == 3


def test_binance_tracker_adverse_selection_jump():
    """Test BinanceTracker jump detection for adverse selection protection."""
    BinanceTracker.btc_ticks.clear()
    t0 = time.monotonic()

    # Steady price around 60,000
    BinanceTracker.record_tick("btc", 60000.0, t0 - 0.4)
    BinanceTracker.record_tick("btc", 60020.0, t0 - 0.2)
    BinanceTracker.record_tick("btc", 60010.0, t0)

    # No jump under 15 bps
    is_jump, bps = BinanceTracker.detect_jump("BTC", window_seconds=0.5, threshold_bps=15.0)
    assert is_jump is False
    assert bps < 15.0

    # Sudden sharp jump (+150 USD = 25 bps)
    BinanceTracker.record_tick("btc", 60160.0, t0 + 0.05)
    is_jump, bps = BinanceTracker.detect_jump("BTC", window_seconds=0.5, threshold_bps=15.0)
    assert is_jump is True
    assert bps >= 20.0


if __name__ == "__main__":
    test_lp_solver_simple_2way()
    test_lp_solver_tennis_bo3()
    test_lp_solver_esports_bo3()
    test_cluster_markets_by_match()
    test_binance_tracker_adverse_selection_jump()
    print("All tests passed successfully!")
