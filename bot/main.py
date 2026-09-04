import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config
from .fpl_client import FPLClient, team_names
from .fixtures import normalize, validate
from .sql_generator import generate, save
from .site import Site
from . import results as results_mod


def save_report(result, gameweek=None):
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)

    if gameweek is not None:
        filename = f"gameweek_{gameweek}_report.json"
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


def finish(result, gameweek=None):
    report_path = save_report(
        result,
        gameweek,
    )

    result["report_file"] = str(report_path)

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


def check_and_apply_results(site, config, latest, dry, result):

    summary = {
        "checked_gameweek": latest,
        "pending_before": 0,
        "updated": [],
        "still_pending_after": [],
    }

    if latest is None:
        result["results"] = summary
        return True

    matches_resp = site.api("matches", latest)
    matches = matches_resp.get("matches", [])

    pending = results_mod.pending_matches(matches)
    summary["pending_before"] = len(pending)

    updates = []

    if pending:
        fpl = FPLClient()
        teams = team_names(fpl.bootstrap())
        raw = fpl.fixtures(latest)

        fpl_index = results_mod.build_fpl_results_index(raw, teams)
        updates = results_mod.finished_updates(pending, fpl_index)

        if dry:
            summary["would_update"] = updates
        else:
            applied = []

            for u in updates:
                site.save_result(
                    u["match_id"],
                    latest,
                    u["home_score"],
                    u["away_score"],
                )

                verify_resp = site.api("matches", latest)
                verify_row = next(
                    (
                        m for m in verify_resp.get("matches", [])
                        if m.get("id") == u["match_id"]
                    ),
                    None,
                )

                if (
                    verify_row is None
                    or verify_row.get("home_score") != u["home_score"]
                    or verify_row.get("away_score") != u["away_score"]
                ):
                    raise RuntimeError(
                        f"Result verification failed for match "
                        f"{u['match_id']} "
                        f"({u['home_team']} vs {u['away_team']})."
                    )

                applied.append(u)

            summary["updated"] = applied

    updated_ids = {u["match_id"] for u in updates}
    still_pending = [m["id"] for m in pending if m["id"] not in updated_ids]

    summary["still_pending_after"] = still_pending

    result["results"] = summary

    return len(still_pending) == 0


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually import the next gameweek and/or save real results.",
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

    try:
        config = load_config()

        with Site(config) as site:

            site.login()

            status = site.api("status")

            latest = status.get(
                "latest_gameweek"
            )

            result[
                "website_latest_gameweek"
            ] = latest

            gameweek_complete = check_and_apply_results(
                site,
                config,
                latest,
                dry,
                result,
            )

            if not gameweek_complete:

                results_found = (
                    result["results"].get("updated")
                    or result["results"].get("would_update")
                    or []
                )

                result.update(
                    {
                        "status": (
                            "SUCCESS - RESULTS ONLY"
                            if not dry
                            else "SUCCESS - PREVIEW (RESULTS ONLY)"
                        ),
                        "message": (
                            f"GW{latest} still has unfinished matches. "
                            f"{len(results_found)} result(s) "
                            + (
                                "updated."
                                if not dry
                                else "would be updated."
                            )
                            + " Next gameweek was not added."
                        ),
                    }
                )

                finish(
                    result,
                    latest,
                )

                return 0

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

                finish(
                    result,
                    target,
                )

                return 0

        fpl = FPLClient()

        bootstrap = fpl.bootstrap()

        teams = {
            int(team["id"]): team["name"]
            for team in bootstrap["teams"]
        }

        raw = fpl.fixtures(target)

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

        sql = generate(fixtures)

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
                    "status": "SUCCESS - PREVIEW",
                    "message": (
                        "Preview only. "
                        "Website was not modified."
                    ),
                }
            )

            finish(
                result,
                target,
            )

            return 0

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

            import_response = site.import_sql(
                target,
                sql,
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
                    "Post-import verification failed."
                )

        result.update(
            {
                "status": (
                    "SUCCESS - VERIFIED"
                ),
                "message": (
                    f"GW{target} imported "
                    "and verified successfully."
                ),
            }
        )

        finish(
            result,
            target,
        )

        return 0

    except Exception as exc:

        result["error"] = (
            f"{type(exc).__name__}: {exc}"
        )

        finish(
            result,
            target if target is not None else latest,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())