"""
USER ACTIVITY + PREDICTION DEADLINE MONITOR.

Read-only monitoring bolted onto the existing bot. It never writes to
matches, predictions, score_exact, users or gameweek_deadlines, never
submits or edits a prediction, and never changes a deadline.

The only write it performs is claiming a notification key through
bot_api.php (`notify_claim`), which is what makes "send this email
exactly once per gameweek" safe when the bot runs every 15 minutes.

Everything here is defensive: run_monitor() never raises. Any failure
is recorded on the report and the rest of the bot carries on untouched.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .notify import send_simple_email


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------


def parse_site_datetime(value, tz):
    """Parse a naive 'YYYY-MM-DD HH:MM:SS' site datetime into the site tz."""

    if not value:
        return None

    text = str(value).strip()

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(text, fmt)
        except ValueError:
            continue

        return naive.replace(tzinfo=ZoneInfo(tz))

    return None


def format_dt(value):
    if value is None:
        return "never"

    return value.strftime("%Y-%m-%d %H:%M")


def format_duration(seconds):
    try:
        total = int(seconds or 0)
    except (TypeError, ValueError):
        return "0m"

    if total <= 0:
        return "0m"

    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60

    if hours:
        return f"{hours}h {minutes}m"

    return f"{minutes}m"


# ---------------------------------------------------------------------------
# activity
# ---------------------------------------------------------------------------


def build_activity_summary(activity_response, config, now):
    """
    Turn the raw /activity payload into the FEATURE 1 + FEATURE 2 report.
    """

    tz = config.site_timezone
    period_days = max(1, int(config.activity_period_days or 7))
    period_start = now - timedelta(days=period_days)

    users = []

    for row in activity_response.get("users", []):
        last_login = parse_site_datetime(row.get("last_login"), tz)
        last_activity = parse_site_datetime(row.get("last_activity"), tz)

        sessions = int(row.get("session_count") or 0)
        active_seconds = int(row.get("total_active_seconds") or 0)

        average_session = (
            active_seconds / sessions if sessions > 0 else 0
        )

        users.append(
            {
                "user_id": row.get("user_id"),
                "username": row.get("username"),
                "email": row.get("email"),
                "last_login": row.get("last_login"),
                "last_login_dt": last_login,
                "login_count": int(row.get("login_count") or 0),
                "last_activity": row.get("last_activity"),
                "last_activity_dt": last_activity,
                "session_count": sessions,
                "total_active_seconds": active_seconds,
                "average_session_seconds": int(average_session),
                "active_in_period": bool(
                    last_login is not None and last_login >= period_start
                ),
                "seen_in_period": bool(
                    last_activity is not None and last_activity >= period_start
                ),
            }
        )

    total_logins = sum(u["login_count"] for u in users)
    total_sessions = sum(u["session_count"] for u in users)
    total_seconds = sum(u["total_active_seconds"] for u in users)

    logged_in_users = [u for u in users if u["login_count"] > 0]

    active_in_period = [u for u in users if u["active_in_period"]]

    never_logged_in = [u for u in users if u["last_login_dt"] is None]

    most_logins = (
        max(logged_in_users, key=lambda u: u["login_count"])
        if logged_in_users
        else None
    )

    timed_users = [u for u in users if u["total_active_seconds"] > 0]

    most_active_by_time = (
        max(timed_users, key=lambda u: u["total_active_seconds"])
        if timed_users
        else None
    )

    least_active = sorted(
        users,
        key=lambda u: (u["login_count"], u["total_active_seconds"]),
    )[:5]

    average_session_seconds = (
        int(total_seconds / total_sessions) if total_sessions else 0
    )

    return {
        "tracking_enabled": bool(
            activity_response.get("activity_tracking")
        ),
        "period_days": period_days,
        "total_users": int(activity_response.get("total_users") or len(users)),
        "users_logged_in_ever": len(logged_in_users),
        "users_active_in_period": len(active_in_period),
        "users_never_logged_in": [u["username"] for u in never_logged_in],
        "total_logins": total_logins,
        "total_sessions": total_sessions,
        "total_active_seconds": total_seconds,
        "average_session_seconds": average_session_seconds,
        "most_logins": (
            {
                "username": most_logins["username"],
                "login_count": most_logins["login_count"],
            }
            if most_logins
            else None
        ),
        "most_active_by_time": (
            {
                "username": most_active_by_time["username"],
                "total_active_seconds": most_active_by_time[
                    "total_active_seconds"
                ],
            }
            if most_active_by_time
            else None
        ),
        "least_active": [
            {
                "username": u["username"],
                "login_count": u["login_count"],
                "total_active_seconds": u["total_active_seconds"],
            }
            for u in least_active
        ],
        "users": users,
    }


# ---------------------------------------------------------------------------
# gameweek completion
# ---------------------------------------------------------------------------


def build_gameweek_summary(gameweek_response, activity_summary, config, now):
    """
    FEATURE 3 + the deadline phase used by FEATURES 4/5.
    """

    tz = config.site_timezone

    deadline = parse_site_datetime(gameweek_response.get("deadline"), tz)

    required = int(gameweek_response.get("required_predictions") or 0)
    total_users = int(gameweek_response.get("total_users") or 0)
    completed = int(gameweek_response.get("completed_users") or 0)

    activity_by_id = {
        u["user_id"]: u for u in activity_summary.get("users", [])
    }

    incomplete = []

    for row in gameweek_response.get("users", []):
        if row.get("completed"):
            continue

        extra = activity_by_id.get(row.get("user_id"), {})

        incomplete.append(
            {
                "user_id": row.get("user_id"),
                "username": row.get("username"),
                "email": row.get("email"),
                "submitted": int(row.get("submitted") or 0),
                "required": required,
                "missing": int(row.get("missing") or 0),
                "last_prediction_at": row.get("last_prediction_at"),
                "last_login": extra.get("last_login"),
                "last_activity": extra.get("last_activity"),
                "total_active_seconds": extra.get("total_active_seconds", 0),
            }
        )

    incomplete.sort(key=lambda u: (-u["missing"], u["username"] or ""))

    completion_rate = (
        round((completed / total_users) * 100.0, 1) if total_users else 0.0
    )

    hours_to_deadline = None
    phase = "unknown"

    if deadline is not None:
        hours_to_deadline = (deadline - now).total_seconds() / 3600.0

        warning = float(config.deadline_warning_hours or 5.0)

        if hours_to_deadline <= 0:
            phase = "passed"
        elif hours_to_deadline <= warning:
            phase = "within_warning_window"
        else:
            phase = "more_than_window_away"

    return {
        "gameweek": gameweek_response.get("gameweek"),
        "deadline": gameweek_response.get("deadline"),
        "deadline_dt": deadline,
        "deadline_source": gameweek_response.get("deadline_source"),
        "hours_to_deadline": (
            round(hours_to_deadline, 2)
            if hours_to_deadline is not None
            else None
        ),
        "phase": phase,
        "required_predictions": required,
        "total_matches": int(gameweek_response.get("total_matches") or 0),
        "premier_league_matches": int(
            gameweek_response.get("premier_league_matches") or 0
        ),
        "other_matches": int(gameweek_response.get("other_matches") or 0),
        "total_users": total_users,
        "completed_users": completed,
        "incomplete_users": total_users - completed,
        "completion_rate": completion_rate,
        "incomplete": incomplete,
    }


# ---------------------------------------------------------------------------
# sanity gate
# ---------------------------------------------------------------------------


def data_is_trustworthy(gameweek_summary):
    """
    SAFETY RULE: never email a report built on nonsense numbers.
    """

    problems = []

    if gameweek_summary.get("gameweek") is None:
        problems.append("No gameweek was resolved.")

    if gameweek_summary.get("deadline_dt") is None:
        problems.append("No deadline could be determined.")

    if gameweek_summary.get("required_predictions", 0) <= 0:
        problems.append("The gameweek has no matches to predict.")

    if gameweek_summary.get("total_users", 0) <= 0:
        problems.append("No users were returned.")

    completed = gameweek_summary.get("completed_users", 0)
    total = gameweek_summary.get("total_users", 0)

    if completed > total:
        problems.append("Completed users exceed total users.")

    return (len(problems) == 0), problems


# ---------------------------------------------------------------------------
# email bodies
# ---------------------------------------------------------------------------


def _user_detail_lines(user, index=None):
    prefix = f"{index}. " if index is not None else "- "

    lines = [
        f"{prefix}{user.get('username')}",
        f"   Email: {user.get('email') or 'n/a'}",
        f"   Predictions: {user.get('submitted')}/{user.get('required')}",
        f"   Missing: {user.get('missing')}",
        f"   Last login: {user.get('last_login') or 'never'}",
        f"   Last activity: {user.get('last_activity') or 'never'}",
        "   Approx. active time: "
        + format_duration(user.get("total_active_seconds")),
    ]

    return lines


def build_warning_email(gameweek_summary, config):
    gw = gameweek_summary["gameweek"]

    hours = config.deadline_warning_hours

    lines = [
        f"GAMEWEEK {gw} - {hours:g} HOURS BEFORE DEADLINE",
        "",
        f"Deadline: {gameweek_summary['deadline']}"
        f" ({config.site_timezone})",
        f"Time left: {gameweek_summary['hours_to_deadline']}h",
        "",
        f"Total users: {gameweek_summary['total_users']}",
        f"Completed predictions: {gameweek_summary['completed_users']}",
        f"Not completed: {gameweek_summary['incomplete_users']}",
        "",
        f"Completion rate: {gameweek_summary['completion_rate']}%",
        "",
        "Required predictions per user: "
        f"{gameweek_summary['required_predictions']} "
        f"({gameweek_summary['premier_league_matches']} Premier League, "
        f"{gameweek_summary['other_matches']} other)",
        "",
    ]

    incomplete = gameweek_summary["incomplete"]

    if not incomplete:
        lines.append("Everyone has completed their predictions.")
    else:
        lines.append("Users who haven't completed predictions:")
        lines.append("")

        for position, user in enumerate(incomplete, start=1):
            lines.extend(_user_detail_lines(user, position))
            lines.append("")

    return "\n".join(lines).rstrip()


def build_passed_email(gameweek_summary, config):
    gw = gameweek_summary["gameweek"]

    lines = [
        f"GAMEWEEK {gw} - DEADLINE PASSED",
        "",
        "Deadline:",
        f"{gameweek_summary['deadline']} ({config.site_timezone})",
        "",
        "Total users:",
        f"{gameweek_summary['total_users']}",
        "",
        "Completed:",
        f"{gameweek_summary['completed_users']}",
        "",
        "Not completed:",
        f"{gameweek_summary['incomplete_users']}",
        "",
        f"Completion rate: {gameweek_summary['completion_rate']}%",
        "",
    ]

    incomplete = gameweek_summary["incomplete"]

    if not incomplete:
        lines.append(
            "Everyone completed their predictions before the deadline."
        )
    else:
        lines.append("Users who did not complete predictions:")
        lines.append("")

        for position, user in enumerate(incomplete, start=1):
            lines.extend(_user_detail_lines(user, position))
            lines.append("")

    lines.append("This is a monitoring report only. No predictions,")
    lines.append("scores or deadlines were modified.")

    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# compact admin report (FEATURE 6)
# ---------------------------------------------------------------------------


def build_admin_report_text(monitor):
    activity = monitor.get("activity") or {}
    gameweek = monitor.get("gameweek") or {}

    phase_labels = {
        "more_than_window_away": "More than the warning window away",
        "within_warning_window": "Within the warning window",
        "passed": "Deadline passed",
        "unknown": "Unknown",
    }

    lines = []

    lines.append("USER ACTIVITY")
    lines.append(f"  Total users: {activity.get('total_users', 0)}")
    lines.append(
        "  Active users "
        f"(last {activity.get('period_days', 7)}d): "
        f"{activity.get('users_active_in_period', 0)}"
    )
    lines.append(f"  Total logins: {activity.get('total_logins', 0)}")

    most_logins = activity.get("most_logins")

    lines.append(
        "  Most logins: "
        + (
            f"{most_logins['username']} ({most_logins['login_count']})"
            if most_logins
            else "n/a"
        )
    )

    most_time = activity.get("most_active_by_time")

    lines.append(
        "  Most active by time: "
        + (
            f"{most_time['username']} "
            f"({format_duration(most_time['total_active_seconds'])})"
            if most_time
            else "n/a"
        )
    )

    lines.append(
        "  Average session time: "
        + format_duration(activity.get("average_session_seconds"))
    )

    if not activity.get("tracking_enabled", False):
        lines.append(
            "  (activity tracking table not installed - "
            "run monitor_install.sql)"
        )

    lines.append("")
    lines.append("PREDICTIONS")
    lines.append(f"  Current gameweek: {gameweek.get('gameweek')}")
    lines.append(f"  Deadline: {gameweek.get('deadline')}")
    lines.append(f"  Users completed: {gameweek.get('completed_users', 0)}")
    lines.append(f"  Users incomplete: {gameweek.get('incomplete_users', 0)}")
    lines.append(
        f"  Completion percentage: {gameweek.get('completion_rate', 0)}%"
    )

    lines.append("")
    lines.append("DEADLINE STATUS")
    lines.append(
        "  " + phase_labels.get(gameweek.get("phase"), "Unknown")
    )

    hours = gameweek.get("hours_to_deadline")

    if hours is not None:
        lines.append(f"  Hours to deadline: {hours}")

    notifications = monitor.get("notifications") or {}

    if notifications:
        lines.append("")
        lines.append("NOTIFICATIONS")

        for key, info in notifications.items():
            lines.append(f"  {key}: {info}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# notification dispatch
# ---------------------------------------------------------------------------


def _claim_and_send(site, config, monitor, key, subject, body):
    """
    Claim the key FIRST (atomic INSERT IGNORE on the website), then send.

    Claiming first means the worst case is a missed email, never a
    duplicate email every 15 minutes.
    """

    notifications = monitor.setdefault("notifications", {})

    try:
        claim = site.api_post("notify_claim", {"key": key})
    except Exception as exc:
        notifications[key] = f"claim failed ({type(exc).__name__}: {exc})"
        return

    if not claim.get("available", False):
        notifications[key] = (
            "not sent - bot_notifications table missing "
            "(run monitor_install.sql)"
        )
        return

    if not claim.get("claimed", False):
        notifications[key] = "already sent earlier - skipped"
        return

    sent, detail = send_simple_email(config, subject, body)

    notifications[key] = "sent" if sent else f"send failed: {detail}"


def maybe_notify(site, config, monitor):
    gameweek_summary = monitor["gameweek"]

    trustworthy, problems = data_is_trustworthy(gameweek_summary)

    if not trustworthy:
        monitor["notifications_skipped"] = problems
        return

    gw = gameweek_summary["gameweek"]
    phase = gameweek_summary["phase"]

    if phase == "within_warning_window":
        _claim_and_send(
            site,
            config,
            monitor,
            f"gw{gw}:deadline_warning",
            f"[FPL Bot] GW{gw} - "
            f"{config.deadline_warning_hours:g}h before deadline "
            f"({gameweek_summary['completion_rate']}% complete)",
            build_warning_email(gameweek_summary, config),
        )

        return

    if phase == "passed":
        hours_past = abs(gameweek_summary["hours_to_deadline"] or 0)

        max_age = float(config.deadline_passed_max_age_hours or 72.0)

        if hours_past > max_age:
            monitor["notifications_skipped"] = [
                f"Deadline passed {hours_past:.1f}h ago, older than "
                f"DEADLINE_PASSED_MAX_AGE_HOURS={max_age:g}."
            ]
            return

        _claim_and_send(
            site,
            config,
            monitor,
            f"gw{gw}:deadline_passed",
            f"[FPL Bot] GW{gw} - deadline passed "
            f"({gameweek_summary['incomplete_users']} missed)",
            build_passed_email(gameweek_summary, config),
        )


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def run_monitor(site, config, result):
    """
    Runs the whole monitor. NEVER raises.

    On success `result["monitor"]` holds the compact admin report data
    and `result["monitor_report"]` holds its text form.
    """

    if not getattr(config, "monitor_enabled", True):
        result["monitor"] = {"enabled": False}
        return

    monitor = {"enabled": True}

    try:
        now = datetime.now(ZoneInfo(config.site_timezone))

        # 1-4. read users, activity, gameweek, deadline and predictions
        activity_response = site.api("activity")
        gameweek_response = site.api("gameweek_report")

        # 5-6. calculate and verify
        activity_summary = build_activity_summary(
            activity_response,
            config,
            now,
        )

        gameweek_summary = build_gameweek_summary(
            gameweek_response,
            activity_summary,
            config,
            now,
        )

        monitor["activity"] = activity_summary
        monitor["gameweek"] = gameweek_summary

        # 7. only now consider sending anything
        maybe_notify(site, config, monitor)

    except Exception as exc:
        monitor["error"] = f"{type(exc).__name__}: {exc}"

        result["monitor"] = _strip_datetimes(monitor)
        result["monitor_report"] = (
            "Monitor failed: " + monitor["error"]
        )

        return

    result["monitor"] = _strip_datetimes(monitor)
    result["monitor_report"] = build_admin_report_text(monitor)


def _strip_datetimes(value):
    """Remove non-JSON-serialisable datetime objects before saving."""

    if isinstance(value, dict):
        return {
            key: _strip_datetimes(item)
            for key, item in value.items()
            if not key.endswith("_dt")
        }

    if isinstance(value, list):
        return [_strip_datetimes(item) for item in value]

    if isinstance(value, datetime):
        return value.isoformat()

    return value