import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)

    if value is None or not value.strip():
        return default

    try:
        return float(value.strip())
    except ValueError:
        return default


def _join_url(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


@dataclass(frozen=True)
class Config:
    website_url: str

    admin_email: str
    admin_password: str

    admin_login_path: str
    admin_page_path: str
    bot_api_path: str

    bot_api_token: str

    site_timezone: str

    headless: bool
    import_confirm: bool
    allow_unsafe_site: bool

    sportmonks_api_token: str

    whatsapp_phone: str
    whatsapp_apikey: str

    # ---- gap-gating (personal WhatsApp report) ----
    whatsapp_gap_hours: float

    # ---- gameweek leaderboard screenshot ----
    leaderboard_page_path: str
    leaderboard_gw_param: str
    leaderboard_table_selector: str

    # ---- WhatsApp GROUP screenshot delivery (Green API) ----
    greenapi_id_instance: str
    greenapi_api_token: str
    whatsapp_group_id: str

    @property
    def sportmonks_enabled(self) -> bool:
        return bool(self.sportmonks_api_token.strip())

    @property
    def group_screenshot_enabled(self) -> bool:
        return bool(
            self.greenapi_id_instance.strip()
            and self.greenapi_api_token.strip()
            and self.whatsapp_group_id.strip()
        )

    @property
    def login_url(self) -> str:

        override = os.getenv("LOGIN_URL")

        if override and override.strip():
            return override.strip()

        return _join_url(self.website_url, self.admin_login_path)

    @property
    def admin_url(self) -> str:
        return _join_url(self.website_url, self.admin_page_path)

    @property
    def api_url(self) -> str:
        return _join_url(self.website_url, self.bot_api_path)

    def leaderboard_url(self, gameweek) -> str:
        base = _join_url(self.website_url, self.leaderboard_page_path)
        return f"{base}?{self.leaderboard_gw_param}={gameweek}"


def load_config() -> Config:
    required = {
        "WEBSITE_URL": os.getenv("WEBSITE_URL"),
        "ADMIN_EMAIL": os.getenv("ADMIN_EMAIL"),
        "ADMIN_PASSWORD": os.getenv("ADMIN_PASSWORD"),
        "BOT_API_PATH": os.getenv("BOT_API_PATH"),
        "BOT_API_TOKEN": os.getenv("BOT_API_TOKEN"),
        "SITE_TIMEZONE": os.getenv("SITE_TIMEZONE"),
    }

    missing = [
        name
        for name, value in required.items()
        if not value or not value.strip()
    ]

    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
        )

    return Config(
        website_url=required["WEBSITE_URL"].rstrip("/"),

        admin_email=required["ADMIN_EMAIL"],
        admin_password=required["ADMIN_PASSWORD"],

        admin_login_path=(
            os.getenv("ADMIN_LOGIN_PATH")
            or "/login.php"
        ),

        admin_page_path=(
            os.getenv("ADMIN_PAGE_PATH")
            or "/myAdmin.php"
        ),

        bot_api_path=required["BOT_API_PATH"],

        bot_api_token=required["BOT_API_TOKEN"],

        site_timezone=required["SITE_TIMEZONE"],

        headless=env_bool(
            "HEADLESS",
            True,
        ),

        import_confirm=env_bool(
            "IMPORT_CONFIRM",
            False,
        ),

        allow_unsafe_site=env_bool(
            "ALLOW_UNSAFE_SITE",
            False,
        ),

        sportmonks_api_token=(
            os.getenv("SPORTMONKS_API_TOKEN")
            or ""
        ).strip(),

        whatsapp_phone=(
            os.getenv("WHATSAPP_PHONE")
            or ""
        ).strip(),

        whatsapp_apikey=(
            os.getenv("WHATSAPP_APIKEY")
            or ""
        ).strip(),

        whatsapp_gap_hours=env_float(
            "WHATSAPP_GAP_HOURS",
            24.0,
        ),

        leaderboard_page_path=(
            os.getenv("LEADERBOARD_PAGE_PATH")
            or "/leaderboard.php"
        ).strip(),

        leaderboard_gw_param=(
            os.getenv("LEADERBOARD_GW_PARAM")
            or "gameweek"
        ).strip(),

        leaderboard_table_selector=(
            os.getenv("LEADERBOARD_TABLE_SELECTOR")
            or "table"
        ).strip(),

        greenapi_id_instance=(
            os.getenv("GREENAPI_ID_INSTANCE")
            or ""
        ).strip(),

        greenapi_api_token=(
            os.getenv("GREENAPI_API_TOKEN")
            or ""
        ).strip(),

        whatsapp_group_id=(
            os.getenv("WHATSAPP_GROUP_ID")
            or ""
        ).strip(),
    )