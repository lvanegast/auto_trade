"""
Shared event ID normalization for cross-platform matching.

All feeders MUST use this module to generate event_ids so that
Limitless, Kalshi, and Polymarket books for the same real-world
event share the exact same event_id in cross_platform_tracker.
"""

import re


def normalize_match_name(title: str) -> str:
    """
    Normalize a match title to a canonical slug.
    
    Examples:
        "FRND, Bayern München vs Aston Villa" → "aston-villa-vs-bayern-munich"
        "Aston Villa vs Bayern Munich" → "aston-villa-vs-bayern-munich"  (sorted)
    """
    normalized = title.lower().strip()
    
    # Strip common prefixes like 'FRND, ', 'FRIENDLIES - ', 'CLUB FRIENDLIES: '
    if "," in normalized:
        normalized = normalized.split(",")[-1].strip()
    if ":" in normalized:
        normalized = normalized.split(":")[-1].strip()
        
    normalized = normalized.replace(".", "").replace(",", "")
    normalized = normalized.replace("vs.", "vs")
    
    # Team synonym mapping to ensure identical slugs across platforms
    synonyms = {
        "münchen": "munich",
        "muenchen": "munich",
        "bayern münchen": "bayern munich",
        "bayern muenchen": "bayern munich",
    }
    for k, v in synonyms.items():
        normalized = normalized.replace(k, v)

    normalized = re.sub(r'\s+', ' ', normalized)

    parts = normalized.split(" vs ")
    if len(parts) == 2:
        team_a = parts[0].strip()
        team_b = parts[1].strip()
        if team_a > team_b:
            team_a, team_b = team_b, team_a
        team_a = team_a.replace(" ", "-")
        team_b = team_b.replace(" ", "-")
        return f"{team_a}-vs-{team_b}"
    else:
        return normalized.replace(" ", "-")


def normalize_outcome(outcome: str) -> str:
    """
    Normalize an outcome title for cross-platform matching.
    
    Handles platform-specific formats:
        Kalshi: "Will SC Freiburg win the match?" → "sc-freiburg"
        Kalshi: "SC Freiburg wins by over 1.5 runs" → "sc-freiburg"
        Kalshi: "Ben Shelton win the Bergs vs Shelton: Round of 32 match?" → "ben-shelton"
        Limitless: "SC Freiburg" → "sc-freiburg"
        Limitless: "3+ total goals" → "3+-total-goals"
        Polymarket: "Will SC Freiburg win?" → "sc-freiburg"
    """
    normalized = outcome.lower().strip()
    normalized = normalized.replace(".", "").replace(",", "")
    
    synonyms = {
        "münchen": "munich",
        "muenchen": "munich",
        "bayern münchen": "bayern munich",
        "bayern muenchen": "bayern munich",
    }
    for k, v in synonyms.items():
        normalized = normalized.replace(k, v)

    normalized = re.sub(r'\s+', ' ', normalized)
    
    # Strip Kalshi/Polymarket question prefixes
    for prefix in ["will ", "does ", "is ", "can "]:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break
    
    # Strip everything after " win the " (Kalshi long format)
    # e.g. "ben shelton win the bergs vs shelton: round of 32 match?" → "ben shelton"
    win_the_match = re.match(r'^(.+?)\s+win\s+the\s+', normalized)
    if win_the_match:
        normalized = win_the_match.group(1)
    else:
        # Strip shorter suffixes
        for suffix in [
            " win the match?",
            " win the match",
            " win?",
            " win",
            " wins",
            " won",
            " to win",
            " winning",
        ]:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)]
                break
    
    # Strip "wins by..." suffix
    normalized = re.sub(r'\s+wins?\s+by\s+.*$', '', normalized)
    normalized = re.sub(r'\s+win\s+by\s+.*$', '', normalized)
    
    normalized = normalized.strip()
    normalized = normalized.replace(" ", "-")
    
    return normalized


def make_match_event_id(match_title: str, outcome_title: str) -> str:
    """
    Generate a canonical event_id for a cross-platform match outcome.
    
    Args:
        match_title: The match/group title (e.g., "SC Freiburg vs Strasbourg")
        outcome_title: The outcome title (e.g., "SC Freiburg" or "Will SC Freiburg win?")
    
    Returns:
        Canonical event_id (e.g., "match_sc-freiburg-vs-strasbourg__sc-freiburg")
    """
    match_slug = normalize_match_name(match_title)
    outcome_slug = normalize_outcome(outcome_title)
    return f"match_{match_slug}__{outcome_slug}"
