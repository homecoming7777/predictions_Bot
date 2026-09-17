"""
Notifications.

The run report is delivered by EMAIL (SMTP), gap-gated: suppressed
while the gap between the last match of the gameweek that just ended
and the first match of the next gameweek is bigger than
REPORT_GAP_HOURS.

A failed or unconfigured send must never fail the bot run - every
function here swallows its own errors and just records what happened
onto the `result` dict for the JSON report.
"""

import mimetypes
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path


def _fmt_gw(value):
    return f"GW{value}" if value is not None else "GW?"


def build_report_message(result: dict) -> str:
    lines = []

    lines.append("Prediction Site Bot")
    lines.append(f"Mode: {result.get('mode', '?')}")
    lines.append(f"Status: {result.get('status', '?')}")

    if result.get("website_latest_gameweek") is not None:
        lines.append(
            f"Checked: {_fmt_gw(result['website_latest_gameweek'])}"
        )

    results_data = result.get("results") or {}

    if results_data:
        updated = (
            results_data.get("updated")
            or results_data.get("would_update")
            or []
        )
        waiting = results_data.get("waiting") or []
        discrepancies = results_data.get("discrepancies") or []
        pl_pending = results_data.get("pending_before_premier_league")
        other_pending = results_data.get("pending_before_other_leagues")

        lines.append(
            f"Results: {len(updated)} updated, "
            f"{len(waiting)} waiting, "
            f"{len(discrepancies)} discrepancies"
        )

        if pl_pending is not None or other_pending is not None:
            lines.append(f"  Premier League pending: {pl_pending or 0}")
            lines.append(f"  Other Leagues pending: {other_pending or 0}")

        if updated:
            lines.append("Updated matches:")
            for u in updated[:20]:
                lines.append(
                    f"  - {u.get('home_team')} "
                    f"{u.get('home_score')}-{u.get('away_score')} "
                    f"{u.get('away_team')}"
                )

        if discrepancies:
            lines.append("Discrepancies found - blocked for safety:")
            for d in discrepancies[:5]:
                lines.append(
                    f"  - {d.get('home_team')} vs {d.get('away_team')}: "
                    f"FPL {d.get('fpl')} / Sportmonks {d.get('sportmonks')}"
                )

    if result.get("next_gameweek_added") is not None:
        lines.append(
            f"{_fmt_gw(result['next_gameweek_added'])} imported and verified."
        )
    elif (
        result.get("target_gameweek") is not None
        and result.get("status") == "STOPPED"
    ):
        lines.append(
            f"{_fmt_gw(result['target_gameweek'])} already existed. No changes."
        )

    if result.get("report_gap_hours") is not None:
        lines.append(
            f"Gap to next kickoff: {result['report_gap_hours']:.1f}h"
        )

    if result.get("message"):
        lines.append(result["message"])

    if result.get("error"):
        lines.append(f"Error: {result['error']}")

    return "\n".join(lines)


def build_email_subject(result: dict) -> str:
    gameweek = (
        result.get("next_gameweek_added")
        or result.get("target_gameweek")
        or result.get("website_latest_gameweek")
    )

    return (
        f"[FPL Bot] {_fmt_gw(gameweek)} - "
        f"{result.get('status', 'UNKNOWN')}"
    )


def _attach_file(message: EmailMessage, path) -> None:
    file_path = Path(path)

    if not file_path.is_file():
        return

    guessed, _ = mimetypes.guess_type(file_path.name)

    maintype, _, subtype = (
        guessed or "application/octet-stream"
    ).partition("/")

    message.add_attachment(
        file_path.read_bytes(),
        maintype=maintype,
        subtype=subtype or "octet-stream",
        filename=file_path.name,
    )


def send_email_report(
    config,
    result: dict,
    allow: bool = True,
    attachments=None,
) -> None:
    """
    Send the personal report by email. Skipped (without touching
    anything else) when `allow` is False - i.e. we are in the quiet
    gap between gameweeks.
    """

    if not allow:
        result["email_sent"] = False
        result["email_skipped_reason"] = (
            "Suppressed: gap to next kickoff is "
            f"{result.get('report_gap_hours', '?')}h, "
            f"above REPORT_GAP_HOURS="
            f"{getattr(config, 'report_gap_hours', 24)}h."
        )
        return

    host = (getattr(config, "smtp_host", "") or "").strip()
    port = int(getattr(config, "smtp_port", 587) or 587)
    username = (getattr(config, "smtp_user", "") or "").strip()
    password = getattr(config, "smtp_password", "") or ""
    mail_from = (getattr(config, "email_from", "") or "").strip() or username
    mail_to_raw = (getattr(config, "email_to", "") or "").strip()

    recipients = [
        address.strip()
        for address in mail_to_raw.replace(";", ",").split(",")
        if address.strip()
    ]

    if not host or not password or not mail_from or not recipients:
        result["email_sent"] = False
        result["email_skipped_reason"] = (
            "SMTP_HOST / SMTP_USER / SMTP_PASSWORD / EMAIL_TO "
            "not configured"
        )
        return

    body = build_report_message(result)

    escaped = (
        body.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

    message = EmailMessage()
    message["Subject"] = build_email_subject(result)
    message["From"] = mail_from
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    message.add_alternative(
        "<html><body>"
        '<pre style="font-family:Menlo,Consolas,monospace;'
        'font-size:13px;line-height:1.5;white-space:pre-wrap;">'
        + escaped
        + "</pre></body></html>",
        subtype="html",
    )

    for path in (attachments or []):
        try:
            _attach_file(message, path)
        except Exception:
            pass

    try:
        context = ssl.create_default_context()

        use_ssl = bool(getattr(config, "smtp_use_ssl", False)) or port == 465

        if use_ssl:
            with smtplib.SMTP_SSL(
                host,
                port,
                context=context,
                timeout=30,
            ) as server:
                if username:
                    server.login(username, password)

                server.send_message(message)

        else:
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.ehlo()

                if bool(getattr(config, "smtp_use_tls", True)):
                    server.starttls(context=context)
                    server.ehlo()

                if username:
                    server.login(username, password)

                server.send_message(message)

        result["email_sent"] = True
        result["email_to"] = recipients

    except Exception as exc:
        result["email_sent"] = False
        result["email_error"] = f"{type(exc).__name__}: {exc}"