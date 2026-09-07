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

    @property
    def sportmonks_enabled(self) -> bool:
        return bool(self.sportmonks_api_token.strip())



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
    )
