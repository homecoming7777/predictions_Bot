import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config
from .fpl_client import FPLClient
from .fixtures import normalize, validate
from .sql_generator import generate, save
from .site import Site


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


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually import the next gameweek.",
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

    try:
        config = load_config()

        # --------------------------------------------------
        # WEBSITE
        # --------------------------------------------------

        with Site(config) as site:

            site.login()

            status = site.api("status")

            latest = status.get(
                "latest_gameweek"
            )

            result[
                "website_latest_gameweek"
            ] = latest

            target = (
                int(latest) + 1
                if latest is not None
                else 1
            )

            result[
                "target_gameweek"
            ] = target

            # --------------------------------------------------
            # GAMEWEEK EXISTS?
            # --------------------------------------------------

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

        # --------------------------------------------------
        # FPL
        # --------------------------------------------------

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

        # --------------------------------------------------
        # NORMALIZE
        # --------------------------------------------------

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

        # --------------------------------------------------
        # SQL
        # --------------------------------------------------

        sql = generate(fixtures)

        sql_path = save(
            sql,
            target,
        )

        result[
            "sql_file"
        ] = str(sql_path)

        # --------------------------------------------------
        # PREVIEW
        # --------------------------------------------------

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

        # --------------------------------------------------
        # EXECUTE
        # --------------------------------------------------

        with Site(config) as site:

            site.login()

            # Safety check
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

            # --------------------------------------------------
            # VERIFY
            # --------------------------------------------------

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
            target,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())