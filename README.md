# FPL Fixture Bot — MyPredictionWebsite

Automates the next Premier League gameweek for the existing PHP/MySQL prediction site.

## Exact rule

The **website's latest Premier League gameweek** is authoritative. If the website has GW5, the bot targets GW6, regardless of what FPL calls its current gameweek.

## Website file

Upload `bot_api.php` beside `connect.php` and replace the token with your own secret. The endpoint provides:

- `status`: latest Premier League GW and next GW
- `exists`: whether the target GW already exists
- `verify`: validates the imported rows

## Local setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
pytest -q
```

Create `.env` from `.env.example`.

Preview only:

```powershell
python -m bot.main
```

Execute:

```powershell
python -m bot.main --execute
```

`IMPORT_CONFIRM=true` is also required for execution.

## GitHub Actions

Create a GitHub repository and upload this project. Add these repository secrets:

- `WEBSITE_URL`
- `ADMIN_EMAIL`
- `ADMIN_PASSWORD`
- `ADMIN_LOGIN_PATH` = `/login.php`
- `ADMIN_PAGE_PATH` = `/myAdmin.php`
- `BOT_API_PATH` = `/bot_api.php`
- `BOT_API_TOKEN` = same token stored in `bot_api.php`
- `SITE_TIMEZONE` = `Africa/Casablanca`

Then Actions → FPL Fixture Sync → Run workflow → **preview**.

Only after preview is correct, run **execute**.

## SQL behavior

Every generated row has:

- team logo fields: `NULL`
- scores: `NULL`
- `deadline`: `NULL`
- `competition`: `Premier League`
- `gameweek`: target gameweek

The centralized deadline remains controlled by your existing `gameweek_deadlines` system.

## Safety

- No FPL account login.
- No DELETE/UPDATE/DROP SQL generated.
- Existing target gameweek stops the run.
- GW39 is impossible; GW38 is the season limit.
- A fixture count other than 10 is a safety stop.
- Post-import verification must pass.
