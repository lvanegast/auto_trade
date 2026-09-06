"""
Devigging Utility Module for Quantitative Odds Analysis.
Provides mathematically rigorous methods to strip bookmaker margin (vig/overround)
from decimal odds to extract fair un-vidded probabilities (p_sharp).

Supported Methods:
1. Multiplicative Devigging (Proportional normalization)
2. Shin's Method (Iterative insider/noise trader model - Shin 1992, 1993)
"""

import math
from typing import List, Tuple, Dict


def devig_multiplicative(odds: List[float]) -> List[float]:
    """
    Strips vig using standard proportional/multiplicative normalization.
    
    p_implied_i = 1 / d_i
    S = sum(p_implied)
    p_fair_i = p_implied_i / S
    """
    if not odds or any(o <= 1.0 for o in odds):
        raise ValueError("All decimal odds must be strictly greater than 1.0")
    
    implied = [1.0 / o for o in odds]
    overround = sum(implied)
    fair_probs = [p / overround for p in implied]
    return fair_probs


def devig_shin(odds: List[float], max_iter: int = 100, tol: float = 1e-7) -> Tuple[List[float], float]:
    """
    Strips vig using Shin's Method (Shin 1992, 1993).
    Solves numerically for the parameter z (proportion of informed traders)
    such that sum(p_fair_i) == 1.0.
    
    Returns:
        (fair_probabilities, z_parameter)
    """
    if not odds or any(o <= 1.0 for o in odds):
        raise ValueError("All decimal odds must be strictly greater than 1.0")
    
    implied = [1.0 / o for o in odds]
    s = sum(implied)
    
    if abs(s - 1.0) < 1e-9:
        return [p for p in implied], 0.0

    def shin_probs_for_z(z_val: float) -> List[float]:
        probs = []
        denom = 2.0 * (1.0 - z_val)
        if abs(denom) < 1e-12:
            return [p / s for p in implied]
        for p_i in implied:
            radicand = z_val**2 + 4.0 * (1.0 - z_val) * (p_i**2 / s)
            term = math.sqrt(max(0.0, radicand))
            probs.append((term - z_val) / denom)
        return probs

    # Binary search for exact parameter z where sum(probs) == 1.0
    z_low, z_high = 0.0, 0.999
    z_mid = 0.0
    
    for _ in range(max_iter):
        z_mid = (z_low + z_high) / 2.0
        probs = shin_probs_for_z(z_mid)
        sum_p = sum(probs)
        
        if abs(sum_p - 1.0) < tol:
            break
        elif sum_p > 1.0:
            z_low = z_mid
        else:
            z_high = z_mid
            
    final_probs = shin_probs_for_z(z_mid)
    sum_final = sum(final_probs)
    normalized_probs = [p / sum_final for p in final_probs]
    
    return normalized_probs, round(z_mid, 6)


def calculate_ev_and_kelly(
    p_sharp: float, p_limitless: float, kelly_fraction: float = 0.5
) -> Dict[str, float]:
    """
    Calculates Expected Value (+EV) and Fractional Kelly position size.
    
    Args:
        p_sharp: Fair probability derived from sharp sportsbook (0.0 to 1.0).
        p_limitless: Entry price on Limitless/prediction market (0.0 to 1.0).
        kelly_fraction: Kelly multiplier (0.5 for Half-Kelly, 0.25 for Quarter-Kelly).
        
    Returns:
        Dict with 'ev_pct', 'is_positive_ev', 'kelly_bankroll_pct'
    """
    if p_limitless <= 0.0 or p_limitless >= 1.0:
        return {"ev_pct": 0.0, "is_positive_ev": False, "kelly_bankroll_pct": 0.0}
    
    # Net payout ratio b per $1 risked
    b = (1.0 - p_limitless) / p_limitless
    
    # EV calculation: Expected Net Profit % per dollar risked
    ev_pct = (p_sharp - p_limitless) / p_limitless
    is_positive_ev = ev_pct > 0.0
    
    # Full Kelly Formula: f* = (p * b - q) / b
    q = 1.0 - p_sharp
    full_kelly = (p_sharp * b - q) / b if b > 0 else 0.0
    full_kelly = max(0.0, full_kelly)
    
    # Fractional Kelly sizing
    kelly_bankroll_pct = round(full_kelly * kelly_fraction, 4)
    
    return {
        "ev_pct": round(ev_pct * 100.0, 2),
        "is_positive_ev": is_positive_ev,
        "kelly_bankroll_pct": kelly_bankroll_pct,
    }
