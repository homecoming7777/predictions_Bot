from __future__ import annotations

import json
import time
from urllib.parse import urlencode

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


class Site:

    def __init__(self, c):
        self.c = c
        self.pw = None
        self.browser = None
        self.context = None
        self.page = None

    def __enter__(self):
        self.pw = sync_playwright().start()

        self.browser = self.pw.chromium.launch(
            headless=self.c.headless
        )

        self.context = self.browser.new_context(
            ignore_https_errors=False,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
        )

        self.page = self.context.new_page()

        return self

    def __exit__(self, *args):
        try:
            if self.context:
                self.context.close()
        finally:
            if self.browser:
                self.browser.close()

            if self.pw:
                self.pw.stop()

    def _body_text(self) -> str:
        try:
            return self.page.locator("body").inner_text(timeout=3000).strip()
        except Exception:
            return ""

    def _is_infinityfree_challenge(self) -> bool:
        text = self._body_text().lower()
        return "this site requires javascript" in text

    def _is_security_warning(self) -> bool:
        url = (self.page.url or "").lower()
        text = self._body_text().lower()

        return (
            url.startswith("chrome-error://chromewebdata")
            or (
                "dangerous site" in text
                and "safe browsing" in text
            )
        )

    def _click_selector(self, selector: str, timeout: int = 3000) -> bool:
        try:
            locator = self.page.locator(selector).first
            locator.wait_for(state="visible", timeout=timeout)
            locator.click(force=True, timeout=timeout)
            return True
        except Exception:
            return False

    def _handle_security_warning(self) -> bool:
        if not self._is_security_warning():
            return False

        if not getattr(self.c, "allow_unsafe_site", False):
            raise RuntimeError(
                "Chrome Safe Browsing blocked the website as a dangerous site. "
                "Set ALLOW_UNSAFE_SITE=true only if this is your own site and "
                "you understand the risk. The recommended fix is to remove the "
                "Safe Browsing warning from the website itself."
            )

        details_selectors = (
            "#details-button",
            "button:has-text('Details')",
            "text=Details",
        )

        details_clicked = False
        for selector in details_selectors:
            if self._click_selector(selector):
                details_clicked = True
                break

        if not details_clicked:
            raise RuntimeError(
                "Chrome showed the Safe Browsing warning, but the Details "
                "button could not be clicked. Run with HEADLESS=false once "
                "to inspect the interstitial."
            )

        self.page.wait_for_timeout(500)

        proceed_selectors = (
            "#proceed-link",
            "a:has-text('this unsafe site')",
            "text=this unsafe site",
        )

        proceed_clicked = False
        for selector in proceed_selectors:
            if self._click_selector(selector):
                proceed_clicked = True
                break

        if not proceed_clicked:
            raise RuntimeError(
                "Chrome showed the Safe Browsing details, but the "
                "'this unsafe site' link could not be clicked. Run with "
                "HEADLESS=false once to inspect the interstitial."
            )

        try:
            self.page.wait_for_load_state(
                "domcontentloaded",
                timeout=30000,
            )
        except PlaywrightTimeoutError:
            pass

        self.page.wait_for_timeout(1500)

        if self._is_security_warning():
            raise RuntimeError(
                "The browser is still on Chrome's Safe Browsing warning "
                "after attempting the bypass."
            )

        return True

    def _wait_for_infinityfree(self, timeout=30000):

        deadline = time.monotonic() + (timeout / 1000)

        while time.monotonic() < deadline:
            if self._is_security_warning():
                self._handle_security_warning()
                continue

            try:
                cookies = self.context.cookies()
                if any(c.get("name") == "__test" for c in cookies):
                    return
            except Exception:
                pass

            if not self._is_infinityfree_challenge():
                return

            self.page.wait_for_timeout(250)

        self.page.wait_for_timeout(2000)

        if self._is_security_warning():
            self._handle_security_warning()

    def _goto(self, url, timeout=60000):
        response = self.page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=timeout,
        )

        if self._is_security_warning():
            self._handle_security_warning()

        self.page.wait_for_timeout(1000)
        self._wait_for_infinityfree(timeout=30000)

        if self._is_infinityfree_challenge():
            self.page.wait_for_timeout(1500)
            self.page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=timeout,
            )
            self.page.wait_for_timeout(1000)

            if self._is_security_warning():
                self._handle_security_warning()

        return response

    def login(self):

        self._goto(self.c.login_url)

        if "login.php" in self.page.url.lower():
            email = self.page.locator('input[name="email"]')
            password = self.page.locator('input[name="password"]')

            email.fill(self.c.admin_email)
            password.fill(self.c.admin_password)

            self.page.locator('button[type="submit"]').click()

            try:
                self.page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=30000,
                )
            except PlaywrightTimeoutError:
                pass

            self.page.wait_for_timeout(1500)

            if self._is_security_warning():
                self._handle_security_warning()

            if "login.php" in self.page.url.lower():
                raise RuntimeError("Website login failed.")

        return True

    def open_admin(self):
        self._goto(self.c.admin_url)
        return self.page.url

    def api(self, action, gw=None):

        params = {
            "action": action,
            "token": self.c.bot_api_token,
        }

        if gw is not None:
            params["gameweek"] = str(gw)

        url = f"{self.c.api_url}?{urlencode(params)}"

        self._goto(url)

        body = self._body_text()

        if not body:
            raise RuntimeError("Website API returned an empty response.")

        if self._is_security_warning():
            self._handle_security_warning()
            body = self._body_text()

        if self._is_infinityfree_challenge():
            self._wait_for_infinityfree()
            self.page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            self.page.wait_for_timeout(1000)
            body = self._body_text()

        try:
            data = json.loads(body.strip())
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Website API returned non-JSON response: "
                + body[:1500]
            ) from exc

        if not data.get("success"):
            raise RuntimeError(
                data.get("error", "Website API error")
            )

        return data

    def import_sql(self, gw, sql):

        params = {
            "action": "import",
            "token": self.c.bot_api_token,
            "gameweek": str(gw),
        }

        url = f"{self.c.api_url}?{urlencode(params)}"

        response = self.context.request.post(
            url,
            form={"sql": sql},
            timeout=120000,
        )

        if not response.ok:
            raise RuntimeError(
                f"Website import HTTP error: {response.status}"
            )

        text = response.text().strip()

        if "This site requires Javascript" in text:
            self._goto(url)
            response = self.context.request.post(
                url,
                form={"sql": sql},
                timeout=120000,
            )
            text = response.text().strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Website import API returned non-JSON response: "
                + text[:1500]
            ) from exc

        if not data.get("success"):
            raise RuntimeError(
                data.get("error", "Website import failed")
            )

        return data

    def save_result(self, match_id, current_gw, home_score, away_score):

        url = self.c.admin_url

        form = {
            "save_result": "1",
            "match_id": str(match_id),
            "current_gw": str(current_gw),
            "home_score": str(home_score),
            "away_score": str(away_score),
        }

        response = self.context.request.post(
            url,
            form=form,
            timeout=60000,
        )

        if not response.ok:
            raise RuntimeError(
                f"Website save_result HTTP error: {response.status}"
            )

        text = response.text()

        if "This site requires Javascript" in text:
            self._goto(url)
            response = self.context.request.post(
                url,
                form=form,
                timeout=60000,
            )
            text = response.text()

        if "login.php" in (response.url or "").lower():
            raise RuntimeError(
                "Website save_result was redirected to the login page. "
                "The admin session may have expired."
            )

        return text