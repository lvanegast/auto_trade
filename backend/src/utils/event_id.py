"""
Shared event ID normalization for cross-platform matching.

All feeders and strategies use this module to generate event_ids so that
Limitless, Kalshi, Polymarket US, and SX Bet books for the same real-world
event share the exact same event_id in cross_platform_tracker.

Powered by SportsMatcher (dr-manhattan inspired semantic normalization).
"""

from src.utils.sports_matcher import SportsMatcher


def normalize_match_name(title: str) -> str:
    """
    Normalize a match title to a canonical slug.
    
    Examples:
        "FRND, Bayern München vs Aston Villa" → "aston-villa-vs-bayern-munich"
        "Man City vs Arsenal" → "arsenal-vs-manchester-city"
        "Arsenal vs Manchester City" → "arsenal-vs-manchester-city"  (sorted)
        "GB @ PIT" → "green-bay-packers-vs-pittsburgh-steelers"
    """
    return SportsMatcher.normalize_match_slug(title)


def normalize_outcome(outcome: str) -> str:
    """
    Normalize an outcome title for cross-platform matching.
    
    Handles platform-specific formats:
        Kalshi: "Will SC Freiburg win the match?" → "sc-freiburg"
        Kalshi: "SC Freiburg wins by over 1.5 runs" → "sc-freiburg"
        Kalshi: "Ben Shelton win the Bergs vs Shelton: Round of 32 match?" → "ben-shelton"
        Limitless: "SC Freiburg" → "sc-freiburg"
        Limitless: "3+ total goals" → "over-2.5-goals"
        Polymarket: "Manchester City (Reg. Time)" → "manchester-city"
        Polymarket: "Draw" / "Tie" → "draw"
    """
    return SportsMatcher.normalize_outcome_slug(outcome)


def make_match_event_id(match_title: str, outcome_title: str) -> str:
    """
    Generate a canonical event_id for a cross-platform match outcome.
    
    Args:
        match_title: The match/group title (e.g., "Man City vs Arsenal")
        outcome_title: The outcome title (e.g., "Manchester City" or "Draw")
    
    Returns:
        Canonical event_id (e.g., "match_arsenal-vs-manchester-city__manchester-city")
    """
    return SportsMatcher.make_event_id(match_title, outcome_title)
