"""
Combinatorial Arbitrage Module with Linear Programming.

Solves the optimal coverage basket for dependent sports sub-markets:
- Tennis: Match Winner + 3+ sets + Over/Under games
- Esports: Match Winner + Map 1 Winner + Map 2 Winner + Total Maps
- Soccer: 3-Way Moneyline (Team A / Team B / Draw) + Over/Under 2.5 + BTTS
- Multi-choice: General 1xN NegRisk

Mathematical Model:
Given K mutually exclusive and collectively exhaustive atomic match states,
and M available contracts with executable ask prices c_j and payout matrix A:
    minimize   sum_{j=1}^M c_j * x_j
    subject to A x >= 1 (payout >= $1.00 in EVERY possible match state)
               x >= 0

Solves via Dual Simplex with zero external dependencies (pure Python list/float arithmetic).
Guaranteed 100% hedge: if min cost c* < 1.00, net profit is guaranteed at settlement.
"""

import math
import os
import re
import time
from typing import Dict, List, Optional, Tuple, Any


class CoveringLPSolver:
    """
    Solves the covering linear program:
        min c^T x  s.t.  A x >= b,  x >= 0
    via the Dual LP:
        max b^T y  s.t.  A^T y <= c,  y >= 0
    where c > 0, b > 0, A >= 0.

    Since c > 0, y = 0 with slack s = c is an immediately feasible
    basic feasible solution (BFS) for the dual. No Phase 1 or artificial
    variables are needed.
    """

    @staticmethod
    def solve(
        costs: List[float],
        matrix: List[List[float]],
        rhs: Optional[List[float]] = None,
        max_iter: int = 150,
        tol: float = 1e-9,
    ) -> Tuple[Optional[List[float]], float, bool, str]:
        """
        Args:
            costs: List of M contract ask prices (all > 0).
            matrix: K x M payout matrix (A[i][j] is payout of contract j in state i).
            rhs: Target payout per state (defaults to 1.0 for all states).
            max_iter: Maximum simplex pivots.
            tol: Numerical tolerance.

        Returns:
            (x_star, optimal_cost, is_optimal, status_msg)
        """
        K = len(matrix)       # States (constraints in primal, variables in dual)
        M = len(costs)        # Contracts (variables in primal, constraints in dual)

        if K == 0 or M == 0:
            return None, 0.0, False, "Empty matrix or costs"

        for c in costs:
            if c <= 0.0:
                return None, 0.0, False, f"Non-positive cost encountered: {c}"

        if rhs is None:
            rhs = [1.0] * K

        # Tableau dimensions:
        # Constraints in dual = M.
        # Variables in dual: K y-variables + M slack variables + 1 RHS column.
        # Total rows = M + 1 (row 0 = objective). Total cols = K + M + 1.
        cols_count = K + M + 1
        rows_count = M + 1
        tableau = [[0.0 for _ in range(cols_count)] for _ in range(rows_count)]

        # Fill dual constraints:
        # for each contract j: sum_i A[i][j] * y_i + s_j = c[j]
        for j in range(M):
            r = j + 1
            for i in range(K):
                tableau[r][i] = float(matrix[i][j])
            tableau[r][K + j] = 1.0      # Slack variable s_j
            tableau[r][-1] = float(costs[j])

        # Objective row 0: max sum_i b[i] * y_i  =>  z - sum_i b[i] * y_i = 0
        for i in range(K):
            tableau[0][i] = -float(rhs[i])

        # Dual Simplex pivoting
        for iteration in range(max_iter):
            # 1. Entering variable: find most negative coefficient in row 0
            pivot_col = -1
            min_c = -tol
            for col in range(K + M):
                if tableau[0][col] < min_c:
                    min_c = tableau[0][col]
                    pivot_col = col

            if pivot_col == -1:
                # Optimal solution found!
                break

            # 2. Minimum ratio test: find exiting variable
            pivot_row = -1
            min_ratio = float("inf")
            for r in range(1, rows_count):
                elem = tableau[r][pivot_col]
                if elem > tol:
                    ratio = tableau[r][-1] / elem
                    if ratio < min_ratio:
                        min_ratio = ratio
                        pivot_row = r

            if pivot_row == -1:
                return None, float("inf"), False, "Dual problem is unbounded (Primal infeasible)"

            # 3. Pivot on (pivot_row, pivot_col)
            pivot_val = tableau[pivot_row][pivot_col]
            for c_idx in range(cols_count):
                tableau[pivot_row][c_idx] /= pivot_val

            for r in range(rows_count):
                if r != pivot_row:
                    factor = tableau[r][pivot_col]
                    if abs(factor) > tol:
                        for c_idx in range(cols_count):
                            tableau[r][c_idx] -= factor * tableau[pivot_row][c_idx]

        optimal_cost = tableau[0][-1]

        # By Strong Duality, primal solution x^* is in row 0 under the slack variables!
        # Slack variable s_j is at column index K + j.
        x_star = [max(0.0, tableau[0][K + j]) for j in range(M)]

        # Verify coverage in every state
        for i in range(K):
            state_payout = sum(matrix[i][j] * x_star[j] for j in range(M))
            if state_payout < rhs[i] - 1e-5:
                return x_star, optimal_cost, False, f"Incomplete coverage in state {i}: payout={state_payout:.4f} < {rhs[i]}"

        return x_star, round(optimal_cost, 6), True, "Optimal"


class CombinatorialArbitrage:
    """
    Analyzes dependent markets for a match and discovers pure combinatorial arbitrage.
    """

    @staticmethod
    def cluster_markets_by_match(markets: List[Any]) -> Dict[str, List[Any]]:
        """
        Groups Limitless market items into clusters sharing the same match event.
        """
        clusters: Dict[str, List[Any]] = {}

        for m in markets:
            title = getattr(m, "title", "") or (m.get("title", "") if isinstance(m, dict) else "")
            slug = getattr(m, "slug", "") or (m.get("slug", "") if isinstance(m, dict) else "")
            if not title or not slug:
                continue

            base = title
            if ":" in base:
                base = base.split(":")[0].strip()
            if "," in base:
                base = base.split(",")[-1].strip()

            soccer_match = re.match(r"^(.*?)\s+and\s+(.*?)\s+(?:both to score|have\s+\d+).*$", base, re.IGNORECASE)
            if soccer_match:
                t1, t2 = soccer_match.group(1).strip(), soccer_match.group(2).strip()
                match_key = f"{t1}-vs-{t2}".lower().replace(" ", "-")
            else:
                parts = base.lower().split(" vs ")
                if len(parts) == 2:
                    p1, p2 = parts[0].strip(), parts[1].strip()
                    if p1 > p2:
                        p1, p2 = p2, p1
                    match_key = f"{p1}-vs-{p2}".replace(" ", "-")
                else:
                    match_key = base.lower().replace(" ", "-")

            clusters.setdefault(match_key, []).append(m)

        return clusters

    @staticmethod
    def build_tennis_bo3_model(
        contracts: List[Dict[str, Any]]
    ) -> Tuple[List[str], List[List[float]]]:
        """
        Builds atomic state space and payoff matrix for Best-of-3 Tennis.
        
        Atomic States (4 states):
            S1: Player 1 wins 2-0 (Sets=2)
            S2: Player 1 wins 2-1 (Sets=3)
            S3: Player 2 wins 2-0 (Sets=2)
            S4: Player 2 wins 2-1 (Sets=3)
        """
        states = [
            "P1_2-0",
            "P1_2-1",
            "P2_2-0",
            "P2_2-1",
        ]
        K = len(states)
        M = len(contracts)
        matrix = [[0.0 for _ in range(M)] for _ in range(K)]

        for j, c in enumerate(contracts):
            ctype = c.get("type", "")
            side = c.get("side", "YES").upper()

            if ctype == "P1_WIN":
                # Pays in S1 and S2
                p1_pay = 1.0 if side == "YES" else 0.0
                p2_pay = 0.0 if side == "YES" else 1.0
                matrix[0][j] = p1_pay
                matrix[1][j] = p1_pay
                matrix[2][j] = p2_pay
                matrix[3][j] = p2_pay
            elif ctype == "P2_WIN":
                p2_pay = 1.0 if side == "YES" else 0.0
                p1_pay = 0.0 if side == "YES" else 1.0
                matrix[0][j] = p1_pay
                matrix[1][j] = p1_pay
                matrix[2][j] = p2_pay
                matrix[3][j] = p2_pay
            elif ctype == "3_SETS":
                # 3+ sets is True in S2 and S4 (3 sets played)
                matrix[0][j] = 0.0 if side == "YES" else 1.0
                matrix[1][j] = 1.0 if side == "YES" else 0.0
                matrix[2][j] = 0.0 if side == "YES" else 1.0
                matrix[3][j] = 1.0 if side == "YES" else 0.0

        return states, matrix

    @staticmethod
    def build_esports_bo3_model(
        contracts: List[Dict[str, Any]]
    ) -> Tuple[List[str], List[List[float]]]:
        """
        Builds atomic state space and payoff matrix for Esports Best-of-3.
        
        Atomic States (6 states):
            S1: T1 wins M1, T1 wins M2 (T1 2-0)
            S2: T1 wins M1, T2 wins M2, T1 wins M3 (T1 2-1)
            S3: T1 wins M1, T2 wins M2, T2 wins M3 (T2 2-1)
            S4: T2 wins M1, T1 wins M2, T1 wins M3 (T1 2-1)
            S5: T2 wins M1, T1 wins M2, T2 wins M3 (T2 2-1)
            S6: T2 wins M1, T2 wins M2 (T2 2-0)
        """
        states = [
            "T1_2-0_M1M2",
            "T1_2-1_M1M3",
            "T2_2-1_M2M3",
            "T1_2-1_M2M3",
            "T2_2-1_M1M3",
            "T2_2-0_M1M2",
        ]
        K = len(states)
        M = len(contracts)
        matrix = [[0.0 for _ in range(M)] for _ in range(K)]

        for j, c in enumerate(contracts):
            ctype = c.get("type", "")
            side = c.get("side", "YES").upper()
            val_yes = 1.0 if side == "YES" else 0.0
            val_no = 0.0 if side == "YES" else 1.0

            if ctype == "T1_MATCH":
                # T1 wins match in S1, S2, S4
                matrix[0][j] = val_yes
                matrix[1][j] = val_yes
                matrix[2][j] = val_no
                matrix[3][j] = val_yes
                matrix[4][j] = val_no
                matrix[5][j] = val_no
            elif ctype == "T2_MATCH":
                # T2 wins match in S3, S5, S6
                matrix[0][j] = val_no
                matrix[1][j] = val_no
                matrix[2][j] = val_yes
                matrix[3][j] = val_no
                matrix[4][j] = val_yes
                matrix[5][j] = val_yes
            elif ctype == "T1_MAP1":
                # T1 wins Map 1 in S1, S2, S3
                matrix[0][j] = val_yes
                matrix[1][j] = val_yes
                matrix[2][j] = val_yes
                matrix[3][j] = val_no
                matrix[4][j] = val_no
                matrix[5][j] = val_no
            elif ctype == "T2_MAP1":
                # T2 wins Map 1 in S4, S5, S6
                matrix[0][j] = val_no
                matrix[1][j] = val_no
                matrix[2][j] = val_no
                matrix[3][j] = val_yes
                matrix[4][j] = val_yes
                matrix[5][j] = val_yes
            elif ctype == "T1_MAP2":
                # T1 wins Map 2 in S1, S4, S5 (and loses in S2, S3, S6)
                matrix[0][j] = val_yes
                matrix[1][j] = val_no
                matrix[2][j] = val_no
                matrix[3][j] = val_yes
                matrix[4][j] = val_yes
                matrix[5][j] = val_no
            elif ctype == "T2_MAP2":
                # T2 wins Map 2 in S2, S3, S6
                matrix[0][j] = val_no
                matrix[1][j] = val_yes
                matrix[2][j] = val_yes
                matrix[3][j] = val_no
                matrix[4][j] = val_no
                matrix[5][j] = val_yes

        return states, matrix

    @classmethod
    async def evaluate_cluster(
        cls,
        match_key: str,
        market_items: List[Any],
        min_net_margin_pct: float = 0.020,
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates a cluster of markets for potential combinatorial arbitrage.
        Fetches executable orderbooks from Limitless price cache and runs LP.
        """
        from src.limitless_price_cache import async_get_limitless_executable_price
        from src.engine.friction_guard import ExecutionFrictionGuard

        contracts: List[Dict[str, Any]] = []

        is_tennis = any("sets" in getattr(m, "title", "").lower() or "games" in getattr(m, "title", "").lower() for m in market_items)
        is_esports = any("map" in getattr(m, "title", "").lower() for m in market_items)

        for m in market_items:
            title = getattr(m, "title", "") or (m.get("title", "") if isinstance(m, dict) else "")
            slug = getattr(m, "slug", "") or (m.get("slug", "") if isinstance(m, dict) else "")
            if not slug:
                continue

            book = await async_get_limitless_executable_price(slug)
            if not book or book.get("ask_size", 0) <= 0 or book.get("bid_size", 0) <= 0:
                continue

            yes_ask = book["yes_ask"]
            no_ask = round(1.0 - book["yes_bid"], 4)
            ask_depth = book.get("ask_size", 0.0)
            bid_depth = book.get("bid_size", 0.0)

            title_l = title.lower()

            if is_tennis:
                if "3 or more total sets" in title_l or "3+ sets" in title_l:
                    contracts.append({"name": f"{title} (YES)", "slug": slug, "type": "3_SETS", "side": "YES", "cost": yes_ask, "depth": ask_depth})
                    contracts.append({"name": f"{title} (NO)", "slug": slug, "type": "3_SETS", "side": "NO", "cost": no_ask, "depth": bid_depth})
                elif "vs" in title_l and ":" not in title_l:
                    contracts.append({"name": f"{title} (Player 1 YES)", "slug": slug, "type": "P1_WIN", "side": "YES", "cost": yes_ask, "depth": ask_depth})
                    contracts.append({"name": f"{title} (Player 2 YES)", "slug": slug, "type": "P2_WIN", "side": "YES", "cost": no_ask, "depth": bid_depth})

            elif is_esports:
                if "map 1" in title_l:
                    contracts.append({"name": f"{title} (T1 Map1 YES)", "slug": slug, "type": "T1_MAP1", "side": "YES", "cost": yes_ask, "depth": ask_depth})
                    contracts.append({"name": f"{title} (T2 Map1 YES)", "slug": slug, "type": "T2_MAP1", "side": "YES", "cost": no_ask, "depth": bid_depth})
                elif "map 2" in title_l:
                    contracts.append({"name": f"{title} (T1 Map2 YES)", "slug": slug, "type": "T1_MAP2", "side": "YES", "cost": yes_ask, "depth": ask_depth})
                    contracts.append({"name": f"{title} (T2 Map2 YES)", "slug": slug, "type": "T2_MAP2", "side": "YES", "cost": no_ask, "depth": bid_depth})
                elif "vs" in title_l and ":" not in title_l:
                    contracts.append({"name": f"{title} (T1 Match YES)", "slug": slug, "type": "T1_MATCH", "side": "YES", "cost": yes_ask, "depth": ask_depth})
                    contracts.append({"name": f"{title} (T2 Match YES)", "slug": slug, "type": "T2_MATCH", "side": "YES", "cost": no_ask, "depth": bid_depth})

        if len(contracts) < 2:
            return None

        if is_tennis and any(c["type"] == "3_SETS" for c in contracts) and any("WIN" in c["type"] for c in contracts):
            states, matrix = cls.build_tennis_bo3_model(contracts)
        elif is_esports and any("MAP" in c["type"] for c in contracts) and any("MATCH" in c["type"] for c in contracts):
            states, matrix = cls.build_esports_bo3_model(contracts)
        else:
            return None

        costs = [c["cost"] for c in contracts]
        x_star, optimal_cost, is_optimal, status = CoveringLPSolver.solve(costs, matrix)

        if not is_optimal or optimal_cost >= 1.00:
            return None

        gross_edge = round(1.00 - optimal_cost, 4)

        fg = ExecutionFrictionGuard()
        active_legs = [contracts[j] for j, x in enumerate(x_star) if x > 0.01]
        num_legs = len(active_legs)

        if num_legs < 2:
            return None

        is_viable, net_edge_pct, reason, friction_info = fg.validate_arbitrage_profitability(
            leg1_feeder="limitless_sports",
            leg2_feeder="limitless_sports",
            gross_edge_pct=gross_edge,
            position_size_usd=10.0,
            execution_role="taker",
            num_legs=num_legs,
        )

        if not is_viable or net_edge_pct < min_net_margin_pct:
            return None

        bottleneck_contracts = min(
            (c["depth"] / max(x_star[j], 0.01) for j, c in enumerate(contracts) if x_star[j] > 0.01),
            default=0.0,
        )

        legs_summary = []
        for j, c in enumerate(contracts):
            if x_star[j] > 0.01:
                qty = round(x_star[j], 3)
                legs_summary.append(f"• Buy {qty:.2f}x {c['name']} @ {c['cost']:.4f}")

        return {
            "match_key": match_key,
            "optimal_cost": optimal_cost,
            "gross_edge_pct": gross_edge,
            "net_edge_pct": net_edge_pct,
            "active_legs": active_legs,
            "legs_summary": "\n".join(legs_summary),
            "bottleneck_size": round(bottleneck_contracts, 2),
            "states_covered": states,
            "num_legs": num_legs,
        }
