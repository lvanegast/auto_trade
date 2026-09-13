"""
Sports Semantic Matcher — Cross-Exchange Entity & Event Normalization.

Inspired by dr-manhattan's cross_exchange/matcher.py and DRADIS ledger.
Resolves cross-platform event discrepancies between Limitless, Polymarket US,
Kalshi, and SX Bet so that identical real-world sports events and outcomes
map to the EXACT same canonical event_id.

Covers:
- Soccer (EPL, La Liga, Serie A, Bundesliga, Ligue 1, UEFA UCL/UEL, MLS)
- Tennis (ATP, WTA)
- Basketball (NBA)
- American Football (NFL)
- Esports (LoL, CS2, Dota 2)
"""

import re
from typing import Dict, List, Optional, Tuple


# =====================================================================
# 1. CANONICAL TEAM / ENTITY ALIAS DICTIONARIES
# =====================================================================

SOCCER_ALIASES: Dict[str, str] = {
    # Premier League
    "man city": "manchester-city",
    "manchester city": "manchester-city",
    "manchester city fc": "manchester-city",
    "mancity": "manchester-city",
    "man utd": "manchester-united",
    "man united": "manchester-united",
    "manchester united": "manchester-united",
    "manchester united fc": "manchester-united",
    "arsenal": "arsenal",
    "arsenal fc": "arsenal",
    "liverpool": "liverpool",
    "liverpool fc": "liverpool",
    "chelsea": "chelsea",
    "chelsea fc": "chelsea",
    "tottenham": "tottenham",
    "tottenham hotspur": "tottenham",
    "tottenham hotspur fc": "tottenham",
    "spurs": "tottenham",
    "newcastle": "newcastle",
    "newcastle united": "newcastle",
    "newcastle united fc": "newcastle",
    "aston villa": "aston-villa",
    "aston villa fc": "aston-villa",
    "wolves": "wolverhampton",
    "wolverhampton": "wolverhampton",
    "wolverhampton wanderers": "wolverhampton",
    "wolverhampton wanderers fc": "wolverhampton",
    "west ham": "west-ham",
    "west ham united": "west-ham",
    "west ham united fc": "west-ham",
    "brighton": "brighton",
    "brighton and hove albion": "brighton",
    "brighton & hove albion": "brighton",
    "bournemouth": "bournemouth",
    "afc bournemouth": "bournemouth",
    "everton": "everton",
    "everton fc": "everton",
    "fulham": "fulham",
    "fulham fc": "fulham",
    "crystal palace": "crystal-palace",
    "crystal palace fc": "crystal-palace",
    "brentford": "brentford",
    "brentford fc": "brentford",
    "nottingham forest": "nottingham-forest",
    "nottingham forest fc": "nottingham-forest",
    "nottm forest": "nottingham-forest",
    "forest": "nottingham-forest",
    "leicester": "leicester",
    "leicester city": "leicester",
    "ipswich": "ipswich",
    "ipswich town": "ipswich",
    "southampton": "southampton",
    "southampton fc": "southampton",

    # La Liga
    "real madrid": "real-madrid",
    "real madrid cf": "real-madrid",
    "madrid": "real-madrid",
    "barcelona": "barcelona",
    "fc barcelona": "barcelona",
    "barca": "barcelona",
    "atletico madrid": "atletico-madrid",
    "atlético madrid": "atletico-madrid",
    "atletico de madrid": "atletico-madrid",
    "atlético de madrid": "atletico-madrid",
    "atleti": "atletico-madrid",
    "sevilla": "sevilla",
    "sevilla fc": "sevilla",
    "real betis": "real-betis",
    "betis": "real-betis",
    "real sociedad": "real-sociedad",
    "villarreal": "villarreal",
    "villarreal cf": "villarreal",
    "athletic bilbao": "athletic-bilbao",
    "athletic club": "athletic-bilbao",
    "valencia": "valencia",
    "valencia cf": "valencia",
    "girona": "girona",
    "girona fc": "girona",

    # Serie A
    "inter": "inter-milan",
    "inter milan": "inter-milan",
    "internazionale": "inter-milan",
    "fc internazionale": "inter-milan",
    "ac milan": "ac-milan",
    "milan": "ac-milan",
    "juventus": "juventus",
    "juve": "juventus",
    "juventus fc": "juventus",
    "napoli": "napoli",
    "ssc napoli": "napoli",
    "roma": "as-roma",
    "as roma": "as-roma",
    "lazio": "lazio",
    "ss lazio": "lazio",
    "atalanta": "atalanta",
    "atalanta bc": "atalanta",
    "fiorentina": "fiorentina",
    "acf fiorentina": "fiorentina",

    # Bundesliga
    "bayern munich": "bayern-munich",
    "bayern münchen": "bayern-munich",
    "bayern muenchen": "bayern-munich",
    "fc bayern": "bayern-munich",
    "fc bayern munich": "bayern-munich",
    "fc bayern münchen": "bayern-munich",
    "borussia dortmund": "borussia-dortmund",
    "dortmund": "borussia-dortmund",
    "bvb": "borussia-dortmund",
    "bvb 09": "borussia-dortmund",
    "bayer leverkusen": "bayer-leverkusen",
    "leverkusen": "bayer-leverkusen",
    "rb leipzig": "rb-leipzig",
    "leipzig": "rb-leipzig",
    "eintracht frankfurt": "eintracht-frankfurt",
    "frankfurt": "eintracht-frankfurt",
    "stuttgart": "vfb-stuttgart",
    "vfb stuttgart": "vfb-stuttgart",
    "sc freiburg": "sc-freiburg",
    "freiburg": "sc-freiburg",

    # Ligue 1 & European Giants
    "psg": "paris-saint-germain",
    "paris saint-germain": "paris-saint-germain",
    "paris saint germain": "paris-saint-germain",
    "paris sg": "paris-saint-germain",
    "marseille": "marseille",
    "olympique de marseille": "marseille",
    "om": "marseille",
    "lyon": "lyon",
    "olympique lyonnais": "lyon",
    "ol": "lyon",
    "monaco": "as-monaco",
    "as monaco": "as-monaco",
    "lille": "lille",
    "losc lille": "lille",
    "sporting cp": "sporting-cp",
    "sporting lisbon": "sporting-cp",
    "sporting": "sporting-cp",
    "benfica": "benfica",
    "sl benfica": "benfica",
    "porto": "fc-porto",
    "fc porto": "fc-porto",
    "ajax": "ajax",
    "afc ajax": "ajax",
    "psv": "psv-eindhoven",
    "psv eindhoven": "psv-eindhoven",
    "feyenoord": "feyenoord",
    "celtic": "celtic",
    "celtic fc": "celtic",
    "rangers": "rangers",
    "rangers fc": "rangers",

    # MLS
    "inter miami": "inter-miami",
    "inter miami cf": "inter-miami",
    "la galaxy": "la-galaxy",
    "los angeles galaxy": "la-galaxy",
    "lafc": "lafc",
    "los angeles fc": "lafc",
    "nycfc": "nycfc",
    "new york city fc": "nycfc",
    "ny red bulls": "new-york-red-bulls",
    "new york red bulls": "new-york-red-bulls",
    "columbus crew": "columbus-crew",
    "seattle sounders": "seattle-sounders",
    "atlanta united": "atlanta-united",
}

TENNIS_ALIASES: Dict[str, str] = {
    # ATP Stars
    "carlos alcaraz": "carlos-alcaraz",
    "c alcaraz": "carlos-alcaraz",
    "alcaraz": "carlos-alcaraz",
    "jannik sinner": "jannik-sinner",
    "j sinner": "jannik-sinner",
    "sinner": "jannik-sinner",
    "novak djokovic": "novak-djokovic",
    "n djokovic": "novak-djokovic",
    "djokovic": "novak-djokovic",
    "alexander zverev": "alexander-zverev",
    "a zverev": "alexander-zverev",
    "zverev": "alexander-zverev",
    "daniil medvedev": "daniil-medvedev",
    "d medvedev": "daniil-medvedev",
    "medvedev": "daniil-medvedev",
    "andrey rublev": "andrey-rublev",
    "a rublev": "andrey-rublev",
    "rublev": "andrey-rublev",
    "casper ruud": "casper-ruud",
    "c ruud": "casper-ruud",
    "ruud": "casper-ruud",
    "hubert hurkacz": "hubert-hurkacz",
    "h hurkacz": "hubert-hurkacz",
    "hurkacz": "hubert-hurkacz",
    "alex de minaur": "alex-de-minaur",
    "a de minaur": "alex-de-minaur",
    "de minaur": "alex-de-minaur",
    "taylor fritz": "taylor-fritz",
    "t fritz": "taylor-fritz",
    "fritz": "taylor-fritz",
    "stefanos tsitsipas": "stefanos-tsitsipas",
    "s tsitsipas": "stefanos-tsitsipas",
    "tsitsipas": "stefanos-tsitsipas",
    "holger rune": "holger-rune",
    "h rune": "holger-rune",
    "rune": "holger-rune",
    "ben shelton": "ben-shelton",
    "b shelton": "ben-shelton",
    "shelton": "ben-shelton",
    "tommy paul": "tommy-paul",
    "t paul": "tommy-paul",
    "grigor dimitrov": "grigor-dimitrov",
    "g dimitrov": "grigor-dimitrov",
    "frances tiafoe": "frances-tiafoe",
    "f tiafoe": "frances-tiafoe",
    "jack draper": "jack-draper",
    "j draper": "jack-draper",

    # WTA Stars
    "iga swiatek": "iga-swiatek",
    "i swiatek": "iga-swiatek",
    "swiatek": "iga-swiatek",
    "aryna sabalenka": "aryna-sabalenka",
    "a sabalenka": "aryna-sabalenka",
    "sabalenka": "aryna-sabalenka",
    "coco gauff": "coco-gauff",
    "c gauff": "coco-gauff",
    "gauff": "coco-gauff",
    "elena rybakina": "elena-rybakina",
    "e rybakina": "elena-rybakina",
    "rybakina": "elena-rybakina",
    "jessica pegula": "jessica-pegula",
    "j pegula": "jessica-pegula",
    "pegula": "jessica-pegula",
    "jasmine paolini": "jasmine-paolini",
    "j paolini": "jasmine-paolini",
    "paolini": "jasmine-paolini",
    "zheng qinwen": "qinwen-zheng",
    "qinwen zheng": "qinwen-zheng",
    "q zheng": "qinwen-zheng",
    "emma navarro": "emma-navarro",
    "e navarro": "emma-navarro",
    "barbora krejcikova": "barbora-krejcikova",
    "b krejcikova": "barbora-krejcikova",
    "daria kasatkina": "daria-kasatkina",
    "d kasatkina": "daria-kasatkina",
    "linda noskova": "linda-noskova",
    "l noskova": "linda-noskova",
}

ESPORTS_ALIASES: Dict[str, str] = {
    "t1": "t1",
    "t1 esports": "t1",
    "gen.g": "geng",
    "geng": "geng",
    "gen g": "geng",
    "gen.g esports": "geng",
    "g2": "g2",
    "g2 esports": "g2",
    "fnatic": "fnatic",
    "fnc": "fnatic",
    "team liquid": "team-liquid",
    "liquid": "team-liquid",
    "cloud9": "cloud9",
    "c9": "cloud9",
    "astralis": "astralis",
    "navi": "navi",
    "natus vincere": "navi",
    "faze": "faze",
    "faze clan": "faze",
    "vitality": "vitality",
    "team vitality": "vitality",
    "bilibili gaming": "bilibili-gaming",
    "blg": "bilibili-gaming",
    "top esports": "top-esports",
    "tes": "top-esports",
    "weibo gaming": "weibo-gaming",
    "wbg": "weibo-gaming",
    "edward gaming": "edg",
    "edg": "edg",
    "damwon kia": "dplus-kia",
    "dk": "dplus-kia",
    "dplus kia": "dplus-kia",
    "kt rolster": "kt-rolster",
    "kt": "kt-rolster",
    "hanwha life": "hle",
    "hanwha life esports": "hle",
    "hle": "hle",
}

US_SPORTS_ALIASES: Dict[str, str] = {
    # NFL
    "gb": "green-bay-packers",
    "green bay": "green-bay-packers",
    "green bay packers": "green-bay-packers",
    "pit": "pittsburgh-steelers",
    "pittsburgh": "pittsburgh-steelers",
    "pittsburgh steelers": "pittsburgh-steelers",
    "kc": "kansas-city-chiefs",
    "kansas city": "kansas-city-chiefs",
    "kansas city chiefs": "kansas-city-chiefs",
    "sf": "san-francisco-49ers",
    "san francisco": "san-francisco-49ers",
    "san francisco 49ers": "san-francisco-49ers",
    "bal": "baltimore-ravens",
    "baltimore": "baltimore-ravens",
    "baltimore ravens": "baltimore-ravens",
    "buf": "buffalo-bills",
    "buffalo": "buffalo-bills",
    "buffalo bills": "buffalo-bills",
    "phi": "philadelphia-eagles",
    "philadelphia": "philadelphia-eagles",
    "philadelphia eagles": "philadelphia-eagles",
    "dal": "dallas-cowboys",
    "dallas": "dallas-cowboys",
    "dallas cowboys": "dallas-cowboys",
    "det": "detroit-lions",
    "detroit": "detroit-lions",
    "detroit lions": "detroit-lions",
    "hou": "houston-texans",
    "houston": "houston-texans",
    "houston texans": "houston-texans",
    "cin": "cincinnati-bengals",
    "cincinnati": "cincinnati-bengals",
    "cincinnati bengals": "cincinnati-bengals",
    "mia": "miami-dolphins",
    "miami": "miami-dolphins",
    "miami dolphins": "miami-dolphins",
    "lar": "los-angeles-rams",
    "los angeles rams": "los-angeles-rams",
    "lac": "los-angeles-chargers",
    "los angeles chargers": "los-angeles-chargers",
    "nyj": "new-york-jets",
    "new york jets": "new-york-jets",
    "nyg": "new-york-giants",
    "new york giants": "new-york-giants",
    "ne": "new-england-patriots",
    "new england": "new-england-patriots",
    "new england patriots": "new-england-patriots",
    "chi": "chicago-bears",
    "chicago bears": "chicago-bears",
    "sea": "seattle-seahawks",
    "seattle seahawks": "seattle-seahawks",

    # NBA
    "bos": "boston-celtics",
    "boston": "boston-celtics",
    "boston celtics": "boston-celtics",
    "lal": "los-angeles-lakers",
    "lakers": "los-angeles-lakers",
    "los angeles lakers": "los-angeles-lakers",
    "gsw": "golden-state-warriors",
    "warriors": "golden-state-warriors",
    "golden state": "golden-state-warriors",
    "golden state warriors": "golden-state-warriors",
    "den": "denver-nuggets",
    "denver": "denver-nuggets",
    "denver nuggets": "denver-nuggets",
    "mil": "milwaukee-bucks",
    "milwaukee": "milwaukee-bucks",
    "milwaukee bucks": "milwaukee-bucks",
    "phx": "phoenix-suns",
    "phoenix": "phoenix-suns",
    "phoenix suns": "phoenix-suns",
    "okc": "oklahoma-city-thunder",
    "oklahoma city": "oklahoma-city-thunder",
    "oklahoma city thunder": "oklahoma-city-thunder",
    "nyk": "new-york-knicks",
    "knicks": "new-york-knicks",
    "new york knicks": "new-york-knicks",
    "min": "minnesota-timberwolves",
    "minnesota": "minnesota-timberwolves",
    "minnesota timberwolves": "minnesota-timberwolves",
    "cle": "cleveland-cavaliers",
    "cleveland": "cleveland-cavaliers",
    "cleveland cavaliers": "cleveland-cavaliers",
    "ind": "indiana-pacers",
    "indiana": "indiana-pacers",
    "indiana pacers": "indiana-pacers",
    "orl": "orlando-magic",
    "orlando": "orlando-magic",
    "orlando magic": "orlando-magic",
}

# Master Combined Lookup
ALL_ALIASES: Dict[str, str] = {
    **SOCCER_ALIASES,
    **TENNIS_ALIASES,
    **ESPORTS_ALIASES,
    **US_SPORTS_ALIASES,
}


# =====================================================================
# 2. MATCH AND OUTCOME NORMALIZER
# =====================================================================

class SportsMatcher:
    """
    Semantic Matcher for Prediction Markets.
    Translates diverse platform event and outcome titles to canonical representations.
    """

    @classmethod
    def clean_text(cls, text: str) -> str:
        """Lowercases, replaces accents/umlauts and strips punctuation."""
        if not text:
            return ""
        s = text.lower().strip()
        # Remove regulation time annotations
        for reg in ["(reg. time)", "(reg time)", "(regulation time)", "reg. time", "reg time"]:
            s = s.replace(reg, " ")
        # Accents & umlauts
        replacements = {
            "ü": "u", "ue": "u", "ä": "a", "ae": "a", "ö": "o", "oe": "o",
            "é": "e", "è": "e", "ê": "e", "á": "a", "à": "a", "í": "i",
            "ó": "o", "ú": "u", "ñ": "n", "ç": "c",
        }
        for k, v in replacements.items():
            s = s.replace(k, v)
        # Dots and other punctuation replaced with space (keep letters, numbers, spaces, @, -, +)
        s = re.sub(r"[^\w\s@\-+]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    @classmethod
    def canonical_entity(cls, name: str) -> str:
        """
        Maps an entity (team name, player name) to its canonical slug.
        """
        cleaned = cls.clean_text(name)
        if not cleaned:
            return ""

        # Direct dictionary match
        if cleaned in ALL_ALIASES:
            return ALL_ALIASES[cleaned]

        # Strip common trailing / leading words like "fc", "cf", "club", "team", "esports"
        words = cleaned.split()
        filtered = [w for w in words if w not in ("fc", "cf", "club", "team", "esports", "gaming")]
        rejoined = " ".join(filtered)
        if rejoined in ALL_ALIASES:
            return ALL_ALIASES[rejoined]

        # Fallback: slugify
        return rejoined.replace(" ", "-") if rejoined else cleaned.replace(" ", "-")

    @classmethod
    def parse_match_parties(cls, title: str) -> Tuple[str, str]:
        """
        Extracts Party A and Party B from match titles supporting multiple notations:
        - "Team A vs Team B"
        - "Team A vs. Team B"
        - "Team A v Team B"
        - "Team A @ Team B" (American: Away @ Home)
        - "FRND, Team A vs Team B"
        - "EPL: Team A vs Team B"
        """
        cleaned = cls.clean_text(title)

        # Remove common prefixes like 'FRND, ', 'FRIENDLIES - ', 'EPL: ', 'UCL - '
        if "," in cleaned:
            cleaned = cleaned.split(",")[-1].strip()
        if ":" in cleaned:
            cleaned = cleaned.split(":")[-1].strip()
        if " - " in cleaned:
            cleaned = cleaned.split(" - ")[-1].strip()

        # Split on separators
        parts = None
        if " vs " in cleaned:
            parts = cleaned.split(" vs ")
        elif " vs. " in cleaned:
            parts = cleaned.split(" vs. ")
        elif " @ " in cleaned:
            # Away @ Home: keep Away as party 1, Home as party 2
            parts = cleaned.split(" @ ")
        elif " v " in cleaned:
            parts = cleaned.split(" v ")

        if parts and len(parts) >= 2:
            party_a = cls.canonical_entity(parts[0].strip())
            party_b = cls.canonical_entity(parts[1].strip())
            return party_a, party_b

        # Single entity or unseparated
        return cls.canonical_entity(cleaned), ""

    @classmethod
    def normalize_match_slug(cls, title: str) -> str:
        """
        Produces a canonical match slug sorted alphabetically so that:
        "Man City vs Arsenal" == "Arsenal vs Manchester City" -> "arsenal-vs-manchester-city"
        """
        party_a, party_b = cls.parse_match_parties(title)
        if party_a and party_b:
            if party_a > party_b:
                party_a, party_b = party_b, party_a
            return f"{party_a}-vs-{party_b}"
        return party_a or cls.clean_text(title).replace(" ", "-")

    @classmethod
    def normalize_outcome_slug(cls, outcome: str) -> str:
        """
        Normalizes an outcome (e.g. Draw, Tie, Team win, Over/Under, Player).
        """
        cleaned = cls.clean_text(outcome)

        # Draw / Tie
        draw_terms = {"draw", "tie", "empate", "x", "draw reg time", "tie reg time"}
        if cleaned in draw_terms or "draw" in cleaned or "tie" in cleaned:
            return "draw"

        # Over / Under goals
        if any(term in cleaned for term in ["3 or more", "3+ total goals", "3+ goals", "over 2 5", "over 2.5"]):
            return "over-2.5-goals"
        if any(term in cleaned for term in ["under 2 5", "under 2.5", "less than 3", "under 2 5 goals", "under 2.5 goals"]):
            return "under-2.5-goals"

        # Both to score
        if "both to score" in cleaned or "both teams to score" in cleaned:
            if "no" in cleaned:
                return "btts-no"
            return "btts-yes"

        # Strip question phrasing
        for prefix in ["will ", "does ", "is ", "can "]:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
                break

        # Kalshi long format: "Team win the Team vs Other: Round of 32 match?"
        win_match = re.match(r"^(.+?)\s+win\s+the\s+", cleaned)
        if win_match:
            cleaned = win_match.group(1).strip()
        else:
            for suffix in [" win the match", " win?", " win", " wins", " won", " to win", " winning"]:
                if cleaned.endswith(suffix):
                    cleaned = cleaned[:-len(suffix)].strip()
                    break

        # Strip "wins by..."
        cleaned = re.sub(r"\s+wins?\s+by\s+.*$", "", cleaned).strip()

        # Check if it matches a canonical team/player
        canonical = cls.canonical_entity(cleaned)
        return canonical if canonical else cleaned.replace(" ", "-")

    @classmethod
    def make_event_id(cls, match_title: str, outcome_title: str) -> str:
        """
        Generates the canonical cross-platform event_id.
        
        Example:
            Limitless: ("Man City vs Arsenal", "Manchester City")
            Polymarket: ("Arsenal vs Manchester City", "Manchester City (Reg. Time)")
            -> Both produce: "match_arsenal-vs-manchester-city__manchester-city"
        """
        match_slug = cls.normalize_match_slug(match_title)
        outcome_slug = cls.normalize_outcome_slug(outcome_title)
        return f"match_{match_slug}__{outcome_slug}"

    @classmethod
    def fuzzy_match_token_similarity(cls, str1: str, str2: str) -> float:
        """
        Computes Jaccard word token similarity between two strings.
        Returns float in [0.0, 1.0].
        """
        t1 = set(cls.clean_text(str1).split())
        t2 = set(cls.clean_text(str2).split())
        if not t1 or not t2:
            return 0.0
        intersection = len(t1.intersection(t2))
        union = len(t1.union(t2))
        return intersection / union
