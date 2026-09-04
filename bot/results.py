"""
Match-result reconciliation.

FPL is the primary provider.

Sportmonks is an independent backup provider.

Safety rules:

1. FPL finished + complete score = usable.
2. FPL finished_provisional + 90 minutes + complete score = usable.
3. Sportmonks final + complete score = usable.
4. If both providers have usable results and disagree -> NEVER update.
5. If no provider has a safe final result -> leave pending.
"""


def pending_matches(matches):
    """
    Site matches that do not yet have a recorded result.
    """

    return [
        m
        for m in matches
        if m.get("home_score") is None
        or m.get("away_score") is None
    ]


def build_fpl_results_index(raw_fixtures, teams):
    """
    Index FPL fixtures by normalized team names.
    """

    index = {}

    for fx in raw_fixtures:
        home_id = fx.get("team_h")
        away_id = fx.get("team_a")

        if home_id is None or away_id is None:
            continue

        try:
            home_id = int(home_id)
            away_id = int(away_id)
        except (TypeError, ValueError):
            continue

        home_name = teams.get(home_id)
        away_name = teams.get(away_id)

        if home_name is None or away_name is None:
            continue

        key = (
            normalize_team(home_name),
            normalize_team(away_name),
        )

        index[key] = {
            "finished": bool(
                fx.get("finished")
            ),
            "finished_provisional": bool(
                fx.get("finished_provisional")
            ),
            "minutes": safe_int(
                fx.get("minutes")
            ),
            "home_score": safe_int(
                fx.get("team_h_score")
            ),
            "away_score": safe_int(
                fx.get("team_a_score")
            ),
            "fpl_fixture_id": fx.get("id"),
            "started": bool(
                fx.get("started")
            ),
        }

    return index


def normalize_team(value):
    """
    Basic normalization for FPL team names.

    Sportmonks has its own stronger normalization in backup_results.py,
    but keeping this function here makes results.py independent and easy
    to test.
    """

    if value is None:
        return ""

    return " ".join(
        str(value)
        .casefold()
        .strip()
        .split()
    )


def safe_int(value):
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fpl_usable_result(fpl_result):
    """
    Return a normalized FPL result if it is safe to use.

    FPL sometimes exposes a real completed score as:
        finished_provisional=true
        finished=false
        minutes=90

    Therefore checking only finished=true is too strict.
    """

    if fpl_result is None:
        return None

    home_score = fpl_result.get(
        "home_score"
    )

    away_score = fpl_result.get(
        "away_score"
    )

    if home_score is None or away_score is None:
        return None

    if fpl_result.get("finished"):
        return {
            "provider": "fpl",
            "confidence": "final",
            "home_score": int(home_score),
            "away_score": int(away_score),
            "fpl_fixture_id": fpl_result.get(
                "fpl_fixture_id"
            ),
        }

    if (
        fpl_result.get("finished_provisional")
        and
        (fpl_result.get("minutes") or 0) >= 90
    ):
        return {
            "provider": "fpl",
            "confidence": "provisional_90",
            "home_score": int(home_score),
            "away_score": int(away_score),
            "fpl_fixture_id": fpl_result.get(
                "fpl_fixture_id"
            ),
        }

    return None


def get_fpl_result(match, fpl_index):
    key = (
        normalize_team(
            match.get("home_team")
        ),
        normalize_team(
            match.get("away_team")
        ),
    )

    return fpl_usable_result(
        fpl_index.get(key)
    )


def compare_results(
    match,
    fpl_result,
    backup_result,
):
    """
    Decide whether a result can safely be saved.

    Returns:
        {
            "status": "update" | "waiting" | "discrepancy",
            ...
        }
    """

    fpl_usable = (
        fpl_result
        if fpl_result
        and fpl_result.get("home_score") is not None
        and fpl_result.get("away_score") is not None
        else None
    )

    backup_usable = (
        backup_result
        if backup_result
        and backup_result.get("status") == "final"
        and backup_result.get("home_score") is not None
        and backup_result.get("away_score") is not None
        else None
    )

    if fpl_usable and backup_usable:

        fpl_score = (
            int(fpl_usable["home_score"]),
            int(fpl_usable["away_score"]),
        )

        backup_score = (
            int(backup_usable["home_score"]),
            int(backup_usable["away_score"]),
        )

        if fpl_score != backup_score:
            return {
                "status": "discrepancy",
                "match_id": match.get("id"),
                "home_team": match.get("home_team"),
                "away_team": match.get("away_team"),
                "fpl": fpl_score,
                "sportmonks": backup_score,
            }

        return {
            "status": "update",
            "match_id": match.get("id"),
            "home_team": match.get("home_team"),
            "away_team": match.get("away_team"),
            "home_score": fpl_score[0],
            "away_score": fpl_score[1],
            "source": "fpl+sportmonks",
            "confidence": "cross_checked",
        }

    if fpl_usable:
        return {
            "status": "update",
            "match_id": match.get("id"),
            "home_team": match.get("home_team"),
            "away_team": match.get("away_team"),
            "home_score": int(
                fpl_usable["home_score"]
            ),
            "away_score": int(
                fpl_usable["away_score"]
            ),
            "source": "fpl",
            "confidence": fpl_usable.get(
                "confidence"
            ),
        }

    if backup_usable:
        return {
            "status": "update",
            "match_id": match.get("id"),
            "home_team": match.get("home_team"),
            "away_team": match.get("away_team"),
            "home_score": int(
                backup_usable["home_score"]
            ),
            "away_score": int(
                backup_usable["away_score"]
            ),
            "source": "sportmonks",
            "confidence": "final",
        }

    return {
        "status": "waiting",
        "match_id": match.get("id"),
        "home_team": match.get("home_team"),
        "away_team": match.get("away_team"),
    }


def finished_updates(
    pending,
    fpl_index,
    backup_results=None,
):
    """
    Legacy-compatible helper.

    If backup_results is supplied, compare both providers.
    Otherwise this behaves as FPL-only reconciliation.
    """

    backup_results = backup_results or {}

    updates = []

    for match in pending:

        fpl_result = get_fpl_result(
            match,
            fpl_index,
        )

        backup_result = backup_results.get(
            match.get("id")
        )

        decision = compare_results(
            match,
            fpl_result,
            backup_result,
        )

        if decision["status"] == "update":
            updates.append(
                decision
            )

    return updates