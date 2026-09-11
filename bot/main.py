import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_config
from .fpl_client import FPLClient, team_names
from .fixtures import normalize, validate
from .sql_generator import generate, save
from .site import Site
from . import results as results_mod
from .backup_results import (
    SportmonksClient,
    find_final_result_for_match,
)
from .notify import (
    send_whatsapp_report,
    send_whatsapp_group_screenshot,
)


def save_report(result, gameweek=None):
    reports_dir = Path("reports")

    reports_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    if gameweek is not None:
        filename = (
            f"gameweek_{gameweek}_report.json"
        )
    else:
        filename = "bot_report.json"

    path = reports_dir / filename

    path.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return path


def _parse_site_datetime(value, tz):
    if not value:
        return None
    try:
        naive = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None
    return naive.replace(tzinfo=ZoneInfo(tz))


def _min_max_match_date(matches, tz):
    dates = [
        _parse_site_datetime(m.get("match_date"), tz)
        for m in matches
    ]
    dates = [d for d in dates if d is not None]
    if not dates:
        return None, None
    return min(dates), max(dates)


def compute_whatsapp_gap(site, config, latest, target, next_fixtures=None):
    """
    Gap (in hours) between the LAST match of the gameweek that just
    ended (`latest`) and the FIRST match of the next gameweek
    (`target`). Used to decide whether the personal WhatsApp report
    should be suppressed while we're deep in the inter-gameweek gap.

    Never raises - any failure here defaults to (None, True) so this
    feature can never silently block a real notification.
    """

    try:
        tz = config.site_timezone

        current_resp = site.api("matches", latest)
        current_matches = current_resp.get("matches", [])
        _, last_dt = _min_max_match_date(current_matches, tz)

        if next_fixtures:
            first_dt = _parse_site_datetime(
                next_fixtures[0]["match_date"], tz
            )
        else:
            next_resp = site.api("matches", target)
            next_matches = next_resp.get("matches", [])
            first_dt, _ = _min_max_match_date(next_matches, tz)

        if last_dt is None or first_dt is None:
            return None, True

        gap_hours = (first_dt - last_dt).total_seconds() / 3600.0

        allow = gap_hours <= config.whatsapp_gap_hours

        return gap_hours, allow

    except Exception:
        return None, True


def maybe_send_group_leaderboard(site, config, latest, results_summary, result):
    """
    If the gameweek that was just checked went from "had pending
    matches" to "fully complete" IN THIS RUN, screenshot the
    leaderboard and send it to the WhatsApp group. Never raises -
    failures are recorded on `result` and the bot keeps going.
    """

    pending_before = results_summary.get("pending_before", 0) or 0
    still_pending_after = results_summary.get("still_pending_after", [])
    discrepancies = results_summary.get("discrepancies", [])

    just_completed = (
        pending_before > 0
        and not still_pending_after
        and not discrepancies
    )

    if not just_completed:
        return

    if not config.group_screenshot_enabled:
        result["group_screenshot_sent"] = False
        result["group_screenshot_skipped_reason"] = (
            "GREENAPI_ID_INSTANCE / GREENAPI_API_TOKEN / "
            "WHATSAPP_GROUP_ID not configured"
        )
        return

    try:
        screenshots_dir = Path("reports")
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        image_path = screenshots_dir / f"gameweek_{latest}_leaderboard.png"

        site.screenshot_leaderboard(latest, config, image_path)

        send_whatsapp_group_screenshot(
            config,
            latest,
            image_path,
            result,
        )

    except Exception as exc:
        result["group_screenshot_sent"] = False
        result["group_screenshot_error"] = f"{type(exc).__name__}: {exc}"


def finish(result, gameweek=None, config=None, allow_personal_whatsapp=True):
    report_path = save_report(
        result,
        gameweek,
    )

    result["report_file"] = str(
        report_path
    )

    if config is not None:
        send_whatsapp_report(
            config,
            result,
            allow=allow_personal_whatsapp,
        )

    report_path.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            result,
            indent=2,
        )
    )


def fetch_backup_results(
    config,
    pending,
    summary,
):
    """
    Query Sportmonks for every pending site match - Premier League and
    Other Leagues alike. Sportmonks matches purely by team name + date,
    so it doesn't care which competition a match belongs to.

    A failed backup API request does NOT automatically fail the entire bot.
    The match simply remains pending unless FPL already has a safe result.
    """

    backup_results = {}

    summary["backup_api"] = {
        "enabled": bool(
            config.sportmonks_enabled
        ),
        "provider": "sportmonks",
        "checked": 0,
        "final": 0,
        "waiting": 0,
        "errors": 0,
        "ambiguous": 0,
    }

    if not config.sportmonks_enabled:
        return backup_results

    try:
        client = SportmonksClient(
            config.sportmonks_api_token
        )
    except Exception as exc:
        summary["backup_api"].update(
            {
                "errors": 1,
                "error": (
                    f"{type(exc).__name__}: {exc}"
                ),
            }
        )

        return backup_results

    for match in pending:

        summary["backup_api"]["checked"] += 1

        try:
            response = find_final_result_for_match(
                client,
                match,
            )

            if response is None:
                summary["backup_api"]["waiting"] += 1
                continue

            status = response.get(
                "status"
            )

            if status == "final":
                backup_results[
                    match["id"]
                ] = response

                summary["backup_api"]["final"] += 1

            elif status == "ambiguous":
                summary["backup_api"][
                    "ambiguous"
                ] += 1

            elif status == "error":
                summary["backup_api"][
                    "errors"
                ] += 1

            else:
                summary["backup_api"][
                    "waiting"
                ] += 1

        except Exception as exc:
            summary["backup_api"][
                "errors"
            ] += 1

            summary.setdefault(
                "backup_errors",
                [],
            ).append(
                {
                    "match_id": match.get("id"),
                    "home_team": match.get(
                        "home_team"
                    ),
                    "away_team": match.get(
                        "away_team"
                    ),
                    "error": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                }
            )

    return backup_results


def _is_premier_league(match):
    return (
        (match.get("competition") or "").strip().casefold()
        == "premier league"
    )


def check_and_apply_results(
    site,
    config,
    latest,
    dry,
    result,
):
    summary = {
        "checked_gameweek": latest,
        "pending_before": 0,
        "updated": [],
        "waiting": [],
        "discrepancies": [],
        "still_pending_after": [],
    }

    if latest is None:
        result["results"] = summary
        return True

    matches_resp = site.api(
        "matches",
        latest,
    )

    all_matches = matches_resp.get(
        "matches",
        [],
    )

    # `matches` (gameweek numbers) are shared across competitions on
    # the site (Premier League + Other Leagues can use the same
    # gameweek number). FPL only ever knows about Premier League
    # fixtures, so it can only ever resolve Premier League rows.
    # Other Leagues rows are resolved through the Sportmonks backup
    # provider instead (see fetch_backup_results / results.compare_results),
    # which matches purely by team name + date and does not care which
    # competition a match belongs to. The gameweek is only considered
    # "complete" - and the next Premier League gameweek only gets
    # imported - once EVERY match this gameweek, across every
    # competition, has a safe final result.
    pl_matches = [
        m for m in all_matches if _is_premier_league(m)
    ]

    other_matches = [
        m for m in all_matches if not _is_premier_league(m)
    ]

    pending_pl = results_mod.pending_matches(pl_matches)
    pending_other = results_mod.pending_matches(other_matches)
    pending = pending_pl + pending_other

    summary["premier_league_matches_this_gameweek"] = len(pl_matches)
    summary["other_league_matches_this_gameweek"] = len(other_matches)
    summary["pending_before"] = len(pending)
    summary["pending_before_premier_league"] = len(pending_pl)
    summary["pending_before_other_leagues"] = len(pending_other)

    # If there is nothing to reconcile, the gameweek is complete.
    if not pending:
        summary["still_pending_after"] = []

        result["results"] = summary

        return True

    # -------------------------------
    # Primary source for Premier League matches: FPL.
    # Other Leagues matches get fpl_result=None below and can only
    # ever be resolved by the Sportmonks backup.
    # -------------------------------

    fpl_index = {}

    if pending_pl:
        fpl = FPLClient()

        teams = team_names(
            fpl.bootstrap()
        )

        # NOTE: this intentionally fetches the WHOLE season's fixtures, not
        # just `latest`. FPL sometimes reschedules a match to a different
        # gameweek than it was originally set for (TV picks, European
        # fixtures, postponements). If we only asked for event=latest, a
        # rescheduled match would never show up here and would stay stuck
        # on "waiting" forever, even after it finished - which is exactly
        # the "already finished but bot says waiting" bug. Matching by
        # (home_team, away_team) is still safe across the whole season
        # because each ordered pair only plays once a season.
        raw = fpl.fixtures_all()

        fpl_index = (
            results_mod.build_fpl_results_index(
                raw,
                teams,
            )
        )

    # -------------------------------
    # Backup source for EVERYONE (Premier League + Other Leagues):
    # Sportmonks
    # -------------------------------

    backup_results = fetch_backup_results(
        config,
        pending,
        summary,
    )

    # -------------------------------
    # Compare providers
    # -------------------------------

    pending_pl_ids = {m["id"] for m in pending_pl}

    decisions = []

    for match in pending:

        fpl_result = (
            results_mod.get_fpl_result(
                match,
                fpl_index,
            )
            if match["id"] in pending_pl_ids
            else None
        )

        backup_result = (
            backup_results.get(
                match["id"]
            )
        )

        decision = (
            results_mod.compare_results(
                match,
                fpl_result,
                backup_result,
            )
        )

        decisions.append(
            decision
        )

    updates = [
        d
        for d in decisions
        if d["status"] == "update"
    ]

    waiting = [
        d
        for d in decisions
        if d["status"] == "waiting"
    ]

    discrepancies = [
        d
        for d in decisions
        if d["status"] == "discrepancy"
    ]

    summary["waiting"] = waiting

    summary["discrepancies"] = (
        discrepancies
    )

    if dry:
        summary["would_update"] = updates

    else:
        applied = []

        for update in updates:

            site.save_result(
                update["match_id"],
                latest,
                update["home_score"],
                update["away_score"],
            )

            # Re-read the website after each update
            # and verify that the actual database value
            # is what we intended to save.
            verify_resp = site.api(
                "matches",
                latest,
            )

            verify_row = next(
                (
                    m
                    for m in verify_resp.get(
                        "matches",
                        [],
                    )
                    if m.get("id")
                    == update["match_id"]
                ),
                None,
            )

            if verify_row is None:
                raise RuntimeError(
                    "Result verification failed: "
                    f"match {update['match_id']} "
                    "was not returned by the website."
                )

            try:
                verified_home = int(
                    verify_row.get(
                        "home_score"
                    )
                )

                verified_away = int(
                    verify_row.get(
                        "away_score"
                    )
                )
            except (
                TypeError,
                ValueError,
            ):
                raise RuntimeError(
                    "Result verification failed: "
                    f"match {update['match_id']} "
                    "returned invalid scores."
                )

            if (
                verified_home
                != update["home_score"]
                or
                verified_away
                != update["away_score"]
            ):
                raise RuntimeError(
                    "Result verification failed for "
                    f"match {update['match_id']} "
                    f"({update['home_team']} vs "
                    f"{update['away_team']}). "
                    f"Expected "
                    f"{update['home_score']}-"
                    f"{update['away_score']}, "
                    f"website has "
                    f"{verified_home}-"
                    f"{verified_away}."
                )

            applied.append(
                update
            )

        summary["updated"] = applied

    # -------------------------------
    # Re-check the website AFTER updates - across EVERY competition,
    # not just Premier League, since the gameweek (and therefore the
    # next Premier League gameweek import) is only "complete" once
    # every match this gameweek has a result.
    # -------------------------------

    if dry:
        updated_ids = {
            d["match_id"]
            for d in updates
        }

        still_pending = [
            m["id"]
            for m in pending
            if m["id"]
            not in updated_ids
        ]

    else:
        final_resp = site.api(
            "matches",
            latest,
        )

        final_matches = final_resp.get(
            "matches",
            [],
        )

        still_pending = [
            m["id"]
            for m in final_matches
            if m.get("home_score") is None
            or m.get("away_score") is None
        ]

    summary[
        "still_pending_after"
    ] = still_pending

    result["results"] = summary

    return len(still_pending) == 0


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Actually import the next gameweek "
            "and/or save real results."
        ),
    )

    args = parser.parse_args()

    dry = not args.execute

    result = {
        "started_at": datetime.now(
            timezone.utc
        ).isoformat(),

        "mode": (
            "PREVIEW"
            if dry
            else "EXECUTE"
        ),

        "status": "FAILED",
    }

    target = None
    latest = None
    config = None

    try:
        config = load_config()

        result[
            "backup_results_provider"
        ] = "sportmonks"

        result[
            "backup_results_enabled"
        ] = config.sportmonks_enabled

        with Site(config) as site:

            site.login()

            status = site.api(
                "status"
            )

            latest = status.get(
                "latest_gameweek"
            )

            result[
                "website_latest_gameweek"
            ] = latest

            gameweek_complete = (
                check_and_apply_results(
                    site,
                    config,
                    latest,
                    dry,
                    result,
                )
            )

            # Fire the WhatsApp GROUP leaderboard screenshot the moment
            # this run is the one that finished off the gameweek (does
            # nothing on every other run, and never touches the
            # personal-report flow above).
            if not dry:
                maybe_send_group_leaderboard(
                    site,
                    config,
                    latest,
                    result.get("results", {}),
                    result,
                )

            if not gameweek_complete:

                results_data = result.get(
                    "results",
                    {},
                )

                results_found = (
                    results_data.get(
                        "updated"
                    )
                    or results_data.get(
                        "would_update"
                    )
                    or []
                )

                discrepancies = (
                    results_data.get(
                        "discrepancies"
                    )
                    or []
                )

                waiting_count = len(
                    results_data.get(
                        "waiting"
                    )
                    or []
                )

                if discrepancies:
                    message = (
                        f"GW{latest} has result "
                        "discrepancies. "
                        f"{len(discrepancies)} "
                        "match(es) were blocked "
                        "for safety. "
                        "Next gameweek was not added."
                    )

                else:
                    message = (
                        f"GW{latest} still has "
                        "unfinished matches. "
                        f"{len(results_found)} "
                        "result(s) "
                        + (
                            "updated."
                            if not dry
                            else "would be updated."
                        )
                        + f" {waiting_count} "
                        "match(es) are still waiting. "
                        "Next gameweek was not added."
                    )

                result.update(
                    {
                        "status": (
                            "SUCCESS - RESULTS ONLY"
                            if not dry
                            else
                            "SUCCESS - PREVIEW "
                            "(RESULTS ONLY)"
                        ),

                        "message": message,
                    }
                )

                finish(
                    result,
                    latest,
                    config,
                )

                return 0

            # -------------------------------
            # Current gameweek is complete
            # -------------------------------

            target = (
                int(latest) + 1
                if latest is not None
                else 1
            )

            result[
                "target_gameweek"
            ] = target

            exists = site.api(
                "exists",
                target,
            )

            if exists.get("exists"):

                result.update(
                    {
                        "status": "STOPPED",
                        "message": (
                            f"GW{target} already exists. "
                            "No changes made."
                        ),
                    }
                )

                gap_hours, allow_personal = compute_whatsapp_gap(
                    site,
                    config,
                    latest,
                    target,
                )

                result["whatsapp_gap_hours"] = gap_hours

                finish(
                    result,
                    target,
                    config,
                    allow_personal_whatsapp=allow_personal,
                )

                return 0

        # -------------------------------
        # FPL fixture import
        # -------------------------------

        fpl = FPLClient()

        bootstrap = fpl.bootstrap()

        teams = {
            int(team["id"]): team["name"]
            for team in bootstrap["teams"]
        }

        raw = fpl.fixtures(
            target
        )

        result[
            "fpl_fixtures_retrieved"
        ] = len(raw)

        fixtures = normalize(
            raw,
            teams,
            config.site_timezone,
            target,
        )

        validate(
            fixtures,
            target,
        )

        result[
            "validated_fixtures"
        ] = len(fixtures)

        sql = generate(
            fixtures
        )

        sql_path = save(
            sql,
            target,
        )

        result[
            "sql_file"
        ] = str(sql_path)

        if dry:

            result.update(
                {
                    "status":
                        "SUCCESS - PREVIEW",

                    "message": (
                        "Preview only. "
                        "Website was not modified."
                    ),
                }
            )

            allow_personal = True

            try:
                with Site(config) as gap_site:
                    gap_site.login()

                    gap_hours, allow_personal = compute_whatsapp_gap(
                        gap_site,
                        config,
                        latest,
                        target,
                        next_fixtures=fixtures,
                    )

                    result["whatsapp_gap_hours"] = gap_hours
            except Exception:
                allow_personal = True

            finish(
                result,
                target,
                config,
                allow_personal_whatsapp=allow_personal,
            )

            return 0

        # -------------------------------
        # Import next gameweek
        # -------------------------------

        with Site(config) as site:

            site.login()

            exists = site.api(
                "exists",
                target,
            )

            if exists.get("exists"):
                raise RuntimeError(
                    "Target gameweek appeared "
                    "before import. "
                    "Import cancelled."
                )

            import_response = (
                site.import_sql(
                    target,
                    sql,
                )
            )

            result[
                "import_response"
            ] = import_response

            verification = site.api(
                "verify",
                target,
            )

            result[
                "verification"
            ] = verification

            if not verification.get(
                "verified"
            ):
                raise RuntimeError(
                    "Post-import verification "
                    "failed."
                )

            gap_hours, allow_personal = compute_whatsapp_gap(
                site,
                config,
                latest,
                target,
                next_fixtures=fixtures,
            )

            result["whatsapp_gap_hours"] = gap_hours

        result.update(
            {
                "status":
                    "SUCCESS - VERIFIED",

                "message": (
                    f"GW{target} imported "
                    "and verified successfully."
                ),

                "next_gameweek_added":
                    target,
            }
        )

        finish(
            result,
            target,
            config,
            allow_personal_whatsapp=allow_personal,
        )

        return 0

    except Exception as exc:

        result["error"] = (
            f"{type(exc).__name__}: {exc}"
        )

        finish(
            result,
            target
            if target is not None
            else latest,
            config,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )