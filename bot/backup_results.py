"""
Sportmonks backup result provider.

This module is deliberately independent from the browser/site code.

The bot uses FPL as the primary source and Sportmonks as a second source
when available.

Important:
- We never trust a Sportmonks result merely because a score exists.
- A fixture must be in a final/full-time state.
- Team names are normalized before matching.
- Multiple possible matches are treated as ambiguous rather than guessed.
"""

from datetime import datetime
import re
import unicodedata

import requests


BASE_URL = "https://api.sportmonks.com/v3/football"


# Common Premier League naming differences between providers.
TEAM_ALIASES = {
    "manchester united": "manchester united",
    "man utd": "manchester united",
    "man united": "manchester united",

    "manchester city": "manchester city",
    "man city": "manchester city",

    "tottenham hotspur": "tottenham hotspur",
    "tottenham": "tottenham hotspur",
    "spurs": "tottenham hotspur",

    "newcastle united": "newcastle united",
    "newcastle": "newcastle united",

    "west ham united": "west ham united",
    "west ham": "west ham united",

    "wolverhampton wanderers": "wolverhampton wanderers",
    "wolves": "wolverhampton wanderers",

    "nottingham forest": "nottingham forest",
    "nott'm forest": "nottingham forest",

    "brighton and hove albion": "brighton and hove albion",
    "brighton": "brighton and hove albion",

    "crystal palace": "crystal palace",

    "afc bournemouth": "afc bournemouth",
    "bournemouth": "afc bournemouth",

    "ipswich town": "ipswich town",
    "ipswich": "ipswich town",

    "leicester city": "leicester city",
    "leicester": "leicester city",

    "nottingham forest": "nottingham forest",

    "fulham": "fulham",
    "arsenal": "arsenal",
    "chelsea": "chelsea",
    "everton": "everton",
    "liverpool": "liverpool",
    "aston villa": "aston villa",
    "brentford": "brentford",
    "burnley": "burnley",
    "leeds united": "leeds united",
    "leeds": "leeds united",
    "sunderland": "sunderland",
}


def normalize_team_name(value):
    """
    Normalize a team name so different providers can be compared safely.
    """

    if value is None:
        return ""

    value = str(value)

    value = unicodedata.normalize(
        "NFKD",
        value,
    )

    value = "".join(
        c
        for c in value
        if not unicodedata.combining(c)
    )

    value = value.casefold().strip()

    value = re.sub(
        r"[^a-z0-9]+",
        " ",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    return TEAM_ALIASES.get(
        value,
        value,
    )


def extract_participants(fixture):
    participants = fixture.get("participants")

    if not isinstance(participants, list):
        return None, None

    home = None
    away = None

    for participant in participants:
        if not isinstance(participant, dict):
            continue

        meta = participant.get("meta") or {}

        location = (
            meta.get("location")
            or participant.get("location")
            or ""
        )

        name = (
            participant.get("name")
            or participant.get("short_code")
            or ""
        )

        location = str(location).lower()

        if location == "home":
            home = name

        elif location == "away":
            away = name

    # Some responses may not have meta.location.
    if home is None or away is None:
        names = [
            p.get("name")
            for p in participants
            if isinstance(p, dict)
            and p.get("name")
        ]

        if len(names) == 2:
            home = home or names[0]
            away = away or names[1]

    return home, away


def extract_score(fixture):
    """
    Extract the CURRENT/FINAL score from Sportmonks scores[].

    We prefer the FT score where available.
    """

    scores = fixture.get("scores")

    if not isinstance(scores, list):
        return None, None

    full_time = None
    current = None

    for score in scores:
        if not isinstance(score, dict):
            continue

        description = str(
            score.get("description")
            or ""
        ).upper()

        score_obj = score.get("score") or {}

        home = score_obj.get("goals")
        away = score_obj.get("goals")

        participant = str(
            score.get("participant")
            or ""
        ).lower()

        # Sportmonks score entries commonly expose
        # goals plus participant. We need both sides.
        if description in {
            "CURRENT",
            "CURRENT SCORE",
        }:
            current = score

        if description in {
            "FT",
            "FULLTIME",
            "FULL TIME",
        }:
            full_time = score

    # Build score from participant-specific entries.
    selected = full_time or current

    if selected is None:
        selected_scores = scores
    else:
        selected_scores = [
            selected
        ]

    home_score = None
    away_score = None

    for score in selected_scores:
        if not isinstance(score, dict):
            continue

        participant = str(
            score.get("participant")
            or ""
        ).lower()

        score_obj = score.get("score") or {}

        goals = score_obj.get("goals")

        if goals is None:
            continue

        try:
            goals = int(goals)
        except (TypeError, ValueError):
            continue

        if participant == "home":
            home_score = goals

        elif participant == "away":
            away_score = goals

    if home_score is not None and away_score is not None:
        return home_score, away_score

    # More defensive fallback:
    # collect participant-specific score records.
    home_score = None
    away_score = None

    for score in scores:
        if not isinstance(score, dict):
            continue

        participant = str(
            score.get("participant")
            or ""
        ).lower()

        score_obj = score.get("score") or {}

        goals = score_obj.get("goals")

        if goals is None:
            continue

        try:
            goals = int(goals)
        except (TypeError, ValueError):
            continue

        description = str(
            score.get("description")
            or ""
        ).upper()

        if description not in {
            "CURRENT",
            "CURRENT SCORE",
            "FT",
            "FULLTIME",
            "FULL TIME",
        }:
            continue

        if participant == "home":
            home_score = goals

        elif participant == "away":
            away_score = goals

    return home_score, away_score


def is_final_fixture(fixture):
    """
    Determine whether Sportmonks considers a fixture final.

    Sportmonks uses state information for fixture state. State 5 is the
    standard Full Time state. We also accept explicit result_info text
    indicating a full-time result.

    We intentionally do NOT accept a live/current score as final.
    """

    state_id = fixture.get("state_id")

    try:
        if int(state_id) == 5:
            return True
    except (TypeError, ValueError):
        pass

    result_info = str(
        fixture.get("result_info")
        or ""
    ).casefold()

    final_phrases = (
        "won after full time",
        "draw after full time",
        "full time",
        "full-time",
        "after full time",
        "after extra time",
        "won on penalties",
    )

    return any(
        phrase in result_info
        for phrase in final_phrases
    )


class SportmonksClient:
    def __init__(self, token):
        token = (token or "").strip()

        if not token:
            raise ValueError(
                "SPORTMONKS_API_TOKEN is empty."
            )

        self.session = requests.Session()

        self.session.headers.update(
            {
                "User-Agent": "FPL-Fixture-Bot/1.0",
                "Accept": "application/json",
                "Authorization": token,
            }
        )

        self.token = token

    def get(self, path, params=None):
        params = dict(params or {})

        response = self.session.get(
            BASE_URL + path,
            params=params,
            timeout=30,
        )

        response.raise_for_status()

        payload = response.json()

        if not isinstance(payload, dict):
            raise RuntimeError(
                "Sportmonks returned an invalid JSON response."
            )

        return payload

    def fixtures_by_date(self, date_value):
        """
        Retrieve Sportmonks fixtures for one calendar date.

        We request participants, scores, state and league so the result
        matching is based on actual structured data.
        """

        return self.get(
            f"/fixtures/date/{date_value}",
            params={
                "include": (
                    "participants;scores;state;league"
                )
            },
        )


def _date_from_match(match):
    value = (
        match.get("match_date")
        or match.get("kickoff")
        or match.get("kickoff_at")
    )

    if not value:
        return None

    value = str(value)

    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).date()
    except ValueError:
        return None


def _fixture_to_result(fixture):
    home, away = extract_participants(
        fixture
    )

    if not home or not away:
        return None

    home_score, away_score = extract_score(
        fixture
    )

    if home_score is None or away_score is None:
        return None

    return {
        "provider": "sportmonks",
        "provider_fixture_id": fixture.get("id"),
        "home_team": home,
        "away_team": away,
        "home_score": int(home_score),
        "away_score": int(away_score),
        "state_id": fixture.get("state_id"),
        "result_info": fixture.get("result_info"),
    }


def find_final_result_for_match(
    client,
    match,
):
    """
    Search Sportmonks by the site's match date and then match teams.

    Returns:
        result dict
        None
        or an error/ambiguous status dict.
    """

    date_value = _date_from_match(match)

    if date_value is None:
        return {
            "status": "error",
            "reason": "invalid_match_date",
        }

    payload = client.fixtures_by_date(
        date_value.isoformat()
    )

    fixtures = payload.get("data")

    if not isinstance(fixtures, list):
        return {
            "status": "error",
            "reason": "invalid_sportmonks_data",
        }

    target_home = normalize_team_name(
        match.get("home_team")
    )

    target_away = normalize_team_name(
        match.get("away_team")
    )

    candidates = []

    for fixture in fixtures:
        if not isinstance(fixture, dict):
            continue

        home, away = extract_participants(
            fixture
        )

        if not home or not away:
            continue

        if (
            normalize_team_name(home) != target_home
            or
            normalize_team_name(away) != target_away
        ):
            continue

        candidates.append(
            fixture
        )

    if not candidates:
        return None

    # If there is more than one same-team fixture on that date,
    # match by kickoff time where possible.
    if len(candidates) > 1:
        target_date = str(
            match.get("match_date")
            or ""
        )

        target_time = (
            target_date[11:16]
            if len(target_date) >= 16
            else None
        )

        if target_time:
            narrowed = []

            for fixture in candidates:
                starting_at = str(
                    fixture.get("starting_at")
                    or ""
                )

                if (
                    len(starting_at) >= 16
                    and
                    starting_at[11:16]
                    == target_time
                ):
                    narrowed.append(
                        fixture
                    )

            if len(narrowed) == 1:
                candidates = narrowed

    if len(candidates) != 1:
        return {
            "status": "ambiguous",
            "reason": "multiple_matching_fixtures",
            "count": len(candidates),
        }

    fixture = candidates[0]

    if not is_final_fixture(fixture):
        return {
            "status": "pending",
            "reason": "sportmonks_not_final",
            "provider_fixture_id": fixture.get("id"),
        }

    result = _fixture_to_result(
        fixture
    )

    if result is None:
        return {
            "status": "pending",
            "reason": "sportmonks_final_without_score",
            "provider_fixture_id": fixture.get("id"),
        }

    result["status"] = "final"

    return result