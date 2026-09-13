"""
Unit tests for SportsMatcher and cross-platform canonical event ID generation.
"""

from src.utils.sports_matcher import SportsMatcher
from src.utils.event_id import normalize_match_name, normalize_outcome, make_match_event_id


def test_soccer_cross_platform_matching():
    """Test EPL & La Liga canonical match and outcome matching."""
    # Limitless says "Man City vs Arsenal"
    id_limitless = make_match_event_id("Man City vs Arsenal", "Manchester City")

    # Polymarket US says "Arsenal vs Manchester City" with outcome "Manchester City (Reg. Time)"
    id_polymarket = make_match_event_id("Arsenal vs Manchester City", "Manchester City (Reg. Time)")

    # Both must resolve to the identical canonical ID!
    assert id_limitless == id_polymarket
    assert id_limitless == "match_arsenal-vs-manchester-city__manchester-city"

    # Draw / Tie matching
    id_draw_limitless = make_match_event_id("Man City vs Arsenal", "Draw")
    id_tie_polymarket = make_match_event_id("Arsenal vs Manchester City", "Tie (Reg. Time)")
    assert id_draw_limitless == id_tie_polymarket
    assert id_draw_limitless == "match_arsenal-vs-manchester-city__draw"

    # Real Madrid vs Barcelona
    id_rm_barca_1 = make_match_event_id("Real Madrid CF vs FC Barcelona", "Real Madrid")
    id_rm_barca_2 = make_match_event_id("Barcelona vs Real Madrid", "Real Madrid CF")
    assert id_rm_barca_1 == id_rm_barca_2
    assert id_rm_barca_1 == "match_barcelona-vs-real-madrid__real-madrid"

    # Over/Under goals matching
    id_ou_1 = make_match_event_id("Liverpool vs Chelsea", "3+ total goals")
    id_ou_2 = make_match_event_id("Chelsea vs Liverpool", "Over 2.5 goals")
    assert id_ou_1 == id_ou_2
    assert id_ou_1 == "match_chelsea-vs-liverpool__over-2.5-goals"


def test_tennis_cross_platform_matching():
    """Test ATP/WTA name variations."""
    # Full name vs abbreviated initial
    id_alcaraz_1 = make_match_event_id("Carlos Alcaraz vs Jannik Sinner", "Carlos Alcaraz")
    id_alcaraz_2 = make_match_event_id("C. Alcaraz vs J. Sinner", "C Alcaraz")
    assert id_alcaraz_1 == id_alcaraz_2
    assert id_alcaraz_1 == "match_carlos-alcaraz-vs-jannik-sinner__carlos-alcaraz"

    # WTA
    id_sabalenka_1 = make_match_event_id("Aryna Sabalenka vs Iga Swiatek", "Aryna Sabalenka")
    id_sabalenka_2 = make_match_event_id("I. Swiatek vs A. Sabalenka", "A Sabalenka")
    assert id_sabalenka_1 == id_sabalenka_2
    assert id_sabalenka_1 == "match_aryna-sabalenka-vs-iga-swiatek__aryna-sabalenka"


def test_us_sports_and_nfl_notation():
    """Test American '@' Away @ Home notation and team abbreviations."""
    # Polymarket often uses "GB @ PIT"
    id_nfl_poly = make_match_event_id("GB @ PIT", "Green Bay Packers")
    id_nfl_limitless = make_match_event_id("Green Bay Packers vs Pittsburgh Steelers", "GB")
    assert id_nfl_poly == id_nfl_limitless
    assert id_nfl_poly == "match_green-bay-packers-vs-pittsburgh-steelers__green-bay-packers"

    # NBA
    id_nba_1 = make_match_event_id("Lakers vs Boston Celtics", "Lakers")
    id_nba_2 = make_match_event_id("BOS @ LAL", "Los Angeles Lakers")
    assert id_nba_1 == id_nba_2
    assert id_nba_1 == "match_boston-celtics-vs-los-angeles-lakers__los-angeles-lakers"


def test_esports_matching():
    """Test Esports tag variations."""
    id_esports_1 = make_match_event_id("T1 vs Gen.G", "T1")
    id_esports_2 = make_match_event_id("Gen.G Esports vs T1 Esports", "T1")
    assert id_esports_1 == id_esports_2
    assert id_esports_1 == "match_geng-vs-t1__t1"


def test_kalshi_question_format_normalization():
    """Test Kalshi-specific question format outcome stripping."""
    kalshi_q = "Will SC Freiburg win the match?"
    normalized = normalize_outcome(kalshi_q)
    assert normalized == "sc-freiburg"

    kalshi_long = "Ben Shelton win the Bergs vs Shelton: Round of 32 match?"
    normalized_long = normalize_outcome(kalshi_long)
    assert normalized_long == "ben-shelton"
