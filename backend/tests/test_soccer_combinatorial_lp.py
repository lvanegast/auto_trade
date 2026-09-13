"""
Unit tests for 9-state Soccer Combinatorial Arbitrage model with Dual Simplex LP.
"""

from src.strategy.combinatorial_arb import CoveringLPSolver, CombinatorialArbitrage


def test_soccer_9_states_completeness():
    """Verify that Soccer model generates exactly 9 atomic states and valid payoff matrix."""
    contracts = [
        {"name": "Team A YES", "slug": "s-1", "type": "TEAM_A_WIN", "side": "YES", "cost": 0.45, "depth": 100},
        {"name": "Team B YES", "slug": "s-1", "type": "TEAM_B_WIN", "side": "YES", "cost": 0.35, "depth": 100},
        {"name": "Draw YES", "slug": "s-1", "type": "DRAW", "side": "YES", "cost": 0.28, "depth": 100},
        {"name": "Over 2.5 YES", "slug": "s-2", "type": "OVER_2_5", "side": "YES", "cost": 0.52, "depth": 100},
        {"name": "Under 2.5 YES", "slug": "s-2", "type": "UNDER_2_5", "side": "YES", "cost": 0.49, "depth": 100},
        {"name": "BTTS YES", "slug": "s-3", "type": "BTTS", "side": "YES", "cost": 0.55, "depth": 100},
        {"name": "BTTS NO", "slug": "s-3", "type": "BTTS", "side": "NO", "cost": 0.46, "depth": 100},
    ]
    states, matrix = CombinatorialArbitrage.build_soccer_model(contracts)

    assert len(states) == 9
    assert len(matrix) == 9
    assert len(matrix[0]) == len(contracts)

    # In every state, the 3 moneyline outcomes must sum to exactly 1.0 (mutually exclusive & exhaustive)
    for state_idx in range(9):
        moneyline_payout = matrix[state_idx][0] + matrix[state_idx][1] + matrix[state_idx][2]
        assert moneyline_payout == 1.0, f"State {states[state_idx]} moneyline sum != 1.0"

        # Over 2.5 + Under 2.5 must sum to exactly 1.0
        ou_payout = matrix[state_idx][3] + matrix[state_idx][4]
        assert ou_payout == 1.0, f"State {states[state_idx]} O/U sum != 1.0"

        # BTTS YES + BTTS NO must sum to exactly 1.0
        btts_payout = matrix[state_idx][5] + matrix[state_idx][6]
        assert btts_payout == 1.0, f"State {states[state_idx]} BTTS sum != 1.0"


def test_soccer_lp_finds_mispricing_across_props():
    """
    Test that when related props (Winner + Under 2.5 + BTTS) are mispriced,
    CoveringLPSolver finds the optimal hedging basket with cost < 1.00.
    """
    # Suppose:
    # Team A Win YES = 0.40
    # Team B Win YES = 0.30
    # Draw YES = 0.25
    # (Sum = 0.95 < 1.00 -> 5% pure 1xN arbitrage)
    contracts = [
        {"name": "Team A YES", "slug": "s-1", "type": "TEAM_A_WIN", "side": "YES", "cost": 0.40, "depth": 100},
        {"name": "Team B YES", "slug": "s-1", "type": "TEAM_B_WIN", "side": "YES", "cost": 0.30, "depth": 100},
        {"name": "Draw YES", "slug": "s-1", "type": "DRAW", "side": "YES", "cost": 0.25, "depth": 100},
        {"name": "Over 2.5 YES", "slug": "s-2", "type": "OVER_2_5", "side": "YES", "cost": 0.58, "depth": 100},
        {"name": "BTTS YES", "slug": "s-3", "type": "BTTS", "side": "YES", "cost": 0.55, "depth": 100},
    ]
    states, matrix = CombinatorialArbitrage.build_soccer_model(contracts)
    costs = [c["cost"] for c in contracts]

    x_star, optimal_cost, is_optimal, status = CoveringLPSolver.solve(costs, matrix)

    assert is_optimal is True
    assert round(optimal_cost, 4) == 0.95
    assert round(x_star[0], 2) == 1.0
    assert round(x_star[1], 2) == 1.0
    assert round(x_star[2], 2) == 1.0
    assert round(x_star[3], 2) == 0.0
    assert round(x_star[4], 2) == 0.0


def test_soccer_lp_composite_hedge():
    """
    Test synthetic composite hedge where buying Over 2.5 + Under 2.5 is cheaper than moneyline.
    """
    contracts = [
        {"name": "Team A YES", "slug": "s-1", "type": "TEAM_A_WIN", "side": "YES", "cost": 0.48, "depth": 100},
        {"name": "Team B YES", "slug": "s-1", "type": "TEAM_B_WIN", "side": "YES", "cost": 0.38, "depth": 100},
        {"name": "Draw YES", "slug": "s-1", "type": "DRAW", "side": "YES", "cost": 0.30, "depth": 100},
        # Over/Under is mispriced: Over (0.44) + Under (0.48) = 0.92 < 1.00!
        {"name": "Over 2.5 YES", "slug": "s-2", "type": "OVER_2_5", "side": "YES", "cost": 0.44, "depth": 100},
        {"name": "Under 2.5 YES", "slug": "s-2", "type": "UNDER_2_5", "side": "YES", "cost": 0.48, "depth": 100},
    ]
    states, matrix = CombinatorialArbitrage.build_soccer_model(contracts)
    costs = [c["cost"] for c in contracts]

    x_star, optimal_cost, is_optimal, status = CoveringLPSolver.solve(costs, matrix)

    assert is_optimal is True
    assert round(optimal_cost, 4) == 0.92
    # Solver must choose Over 2.5 and Under 2.5 to cover all states at 0.92
    assert round(x_star[3], 2) == 1.0
    assert round(x_star[4], 2) == 1.0
    # Moneyline legs should be 0
    assert round(x_star[0], 2) == 0.0
    assert round(x_star[1], 2) == 0.0
    assert round(x_star[2], 2) == 0.0
