from bot.fixtures import normalize
from bot.sql_generator import generate

from bot import results


def test_fixture_and_sql():
    raw = [
        {
            "id": 1,
            "event": 6,
            "team_h": 1,
            "team_a": 2,
            "kickoff_time": "2026-09-05T15:00:00Z",
        }
    ]

    fs = normalize(
        raw,
        {
            1: "Arsenal",
            2: "Liverpool",
        },
        "Africa/Casablanca",
        6,
    )

    s = generate(fs)

    assert "'Arsenal'" in s
    assert "'Liverpool'" in s
    assert (
        ",\n    NULL,\n"
        "    NULL,\n"
        "    6,\n"
        "    NULL"
    ) in s


def test_fpl_finished_result_is_usable():
    fpl = {
        "finished": True,
        "finished_provisional": False,
        "minutes": 90,
        "home_score": 2,
        "away_score": 1,
        "fpl_fixture_id": 123,
    }

    result = results.fpl_usable_result(
        fpl
    )

    assert result is not None
    assert result["home_score"] == 2
    assert result["away_score"] == 1
    assert result["provider"] == "fpl"


def test_fpl_provisional_90_min_result_is_usable():
    """
    This is the important regression test.

    FPL can expose:
        finished=false
        finished_provisional=true
        minutes=90

    with a complete score.

    The old bot rejected this.
    The new bot accepts it.
    """

    fpl = {
        "finished": False,
        "finished_provisional": True,
        "minutes": 90,
        "home_score": 0,
        "away_score": 2,
        "fpl_fixture_id": 21,
    }

    result = results.fpl_usable_result(
        fpl
    )

    assert result is not None
    assert result["home_score"] == 0
    assert result["away_score"] == 2
    assert result["confidence"] == "provisional_90"


def test_fpl_incomplete_score_is_not_usable():
    fpl = {
        "finished": False,
        "finished_provisional": True,
        "minutes": 90,
        "home_score": 0,
        "away_score": None,
    }

    result = results.fpl_usable_result(
        fpl
    )

    assert result is None


def test_provider_agreement_allows_update():
    match = {
        "id": 21,
        "home_team": "Arsenal",
        "away_team": "Liverpool",
    }

    fpl = {
        "provider": "fpl",
        "confidence": "final",
        "home_score": 2,
        "away_score": 1,
    }

    sportmonks = {
        "status": "final",
        "home_score": 2,
        "away_score": 1,
    }

    decision = results.compare_results(
        match,
        fpl,
        sportmonks,
    )

    assert decision["status"] == "update"
    assert decision["home_score"] == 2
    assert decision["away_score"] == 1
    assert decision["confidence"] == "cross_checked"


def test_provider_disagreement_blocks_update():
    match = {
        "id": 21,
        "home_team": "Arsenal",
        "away_team": "Liverpool",
    }

    fpl = {
        "provider": "fpl",
        "confidence": "final",
        "home_score": 2,
        "away_score": 1,
    }

    sportmonks = {
        "status": "final",
        "home_score": 2,
        "away_score": 2,
    }

    decision = results.compare_results(
        match,
        fpl,
        sportmonks,
    )

    assert decision["status"] == "discrepancy"
    assert decision["fpl"] == (2, 1)
    assert decision["sportmonks"] == (2, 2)


def test_backup_can_be_used_when_fpl_is_not_ready():
    match = {
        "id": 21,
        "home_team": "Arsenal",
        "away_team": "Liverpool",
    }

    fpl = None

    sportmonks = {
        "status": "final",
        "home_score": 3,
        "away_score": 0,
    }

    decision = results.compare_results(
        match,
        fpl,
        sportmonks,
    )

    assert decision["status"] == "update"
    assert decision["source"] == "sportmonks"
    assert decision["home_score"] == 3
    assert decision["away_score"] == 0


def test_no_provider_means_waiting():
    match = {
        "id": 21,
        "home_team": "Arsenal",
        "away_team": "Liverpool",
    }

    decision = results.compare_results(
        match,
        None,
        None,
    )

    assert decision["status"] == "waiting"