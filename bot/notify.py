"""
WhatsApp notifications.

1) Personal report -> CallMeBot (text only, unchanged behavior),
   now gap-gated: suppressed while the gap between the last match of
   the gameweek that just ended and the first match of the next
   gameweek is bigger than WHATSAPP_GAP_HOURS.

2) Group leaderboard screenshot -> Green API (supports groups + images,
   which CallMeBot does not).

A failed or unconfigured send must never fail the bot run - every
function here swallows its own errors and just records what happened
onto the `result` dict for the JSON report.
"""

from urllib.parse import quote

import requests


CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"
GREENAPI_BASE_URL = "https://api.green-api.com"


def _fmt_gw(value):
    return f"GW{value}" if value is not None else "GW?"


def build_whatsapp_message(result: dict) -> str:
    lines = []

    lines.append("⚽ *Prediction Site Bot*")
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

        if discrepancies:
            lines.append("⚠️ Discrepancies found - blocked for safety:")
            for d in discrepancies[:5]:
                lines.append(
                    f"  - {d.get('home_team')} vs {d.get('away_team')}: "
                    f"FPL {d.get('fpl')} / Sportmonks {d.get('sportmonks')}"
                )

    if result.get("next_gameweek_added") is not None:
        lines.append(
            f"✅ {_fmt_gw(result['next_gameweek_added'])} imported and verified."
        )
    elif (
        result.get("target_gameweek") is not None
        and result.get("status") == "STOPPED"
    ):
        lines.append(
            f"{_fmt_gw(result['target_gameweek'])} already existed. No changes."
        )

    if result.get("whatsapp_gap_hours") is not None:
        lines.append(
            f"Gap to next kickoff: {result['whatsapp_gap_hours']:.1f}h"
        )

    if result.get("message"):
        lines.append(result["message"])

    if result.get("error"):
        lines.append(f"❌ Error: {result['error']}")

    return "\n".join(lines)


def send_whatsapp_report(config, result: dict, allow: bool = True) -> None:
    """
    Send the personal CallMeBot report. Unchanged CallMeBot behavior,
    except it is skipped (without touching anything else) when `allow`
    is False - i.e. we are in the quiet gap between gameweeks.
    """

    if not allow:
        result["whatsapp_sent"] = False
        result["whatsapp_skipped_reason"] = (
            "Suppressed: gap to next kickoff is "
            f"{result.get('whatsapp_gap_hours', '?')}h, "
            f"above WHATSAPP_GAP_HOURS="
            f"{getattr(config, 'whatsapp_gap_hours', 24)}h."
        )
        return

    phone = getattr(config, "whatsapp_phone", "") or ""
    apikey = getattr(config, "whatsapp_apikey", "") or ""

    if not phone.strip() or not apikey.strip():
        result["whatsapp_sent"] = False
        result["whatsapp_skipped_reason"] = (
            "WHATSAPP_PHONE/WHATSAPP_APIKEY not configured"
        )
        return

    message = build_whatsapp_message(result)

    url = (
        f"{CALLMEBOT_URL}?phone={quote(phone.strip())}"
        f"&text={quote(message)}"
        f"&apikey={quote(apikey.strip())}"
    )

    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        result["whatsapp_sent"] = True
    except Exception as exc:
        result["whatsapp_sent"] = False
        result["whatsapp_error"] = f"{type(exc).__name__}: {exc}"


def send_whatsapp_group_screenshot(
    config,
    gameweek,
    image_path,
    result: dict,
) -> None:
    """
    Send the leaderboard screenshot to the WhatsApp GROUP via Green API
    (https://green-api.com - free dev instance available).

    Required env vars: GREENAPI_ID_INSTANCE, GREENAPI_API_TOKEN,
    WHATSAPP_GROUP_ID (format: "1203630XXXXXXXXX@g.us").
    """

    id_instance = getattr(config, "greenapi_id_instance", "") or ""
    api_token = getattr(config, "greenapi_api_token", "") or ""
    group_id = getattr(config, "whatsapp_group_id", "") or ""

    if not id_instance.strip() or not api_token.strip() or not group_id.strip():
        result["group_screenshot_sent"] = False
        result["group_screenshot_skipped_reason"] = (
            "GREENAPI_ID_INSTANCE / GREENAPI_API_TOKEN / "
            "WHATSAPP_GROUP_ID not configured"
        )
        return

    url = (
        f"{GREENAPI_BASE_URL}/waInstance{id_instance.strip()}"
        f"/sendFileByUpload/{api_token.strip()}"
    )

    caption = f"🏆 *Leaderboard - GW{gameweek}*"

    try:
        with open(image_path, "rb") as file_obj:
            files = {
                "file": (
                    f"gameweek_{gameweek}_leaderboard.png",
                    file_obj,
                    "image/png",
                )
            }

            data = {
                "chatId": group_id.strip(),
                "caption": caption,
            }

            response = requests.post(
                url,
                data=data,
                files=files,
                timeout=60,
            )

            response.raise_for_status()

        result["group_screenshot_sent"] = True

    except Exception as exc:
        result["group_screenshot_sent"] = False
        result["group_screenshot_error"] = f"{type(exc).__name__}: {exc}"