import re,requests
from playwright.sync_api import sync_playwright
class Site:
    def __init__(self,c): self.c=c
    def __enter__(self):
        self.pw=sync_playwright().start();self.browser=self.pw.chromium.launch(headless=self.c.headless);self.page=self.browser.new_page();return self
    def __exit__(self,*a): self.browser.close();self.pw.stop()
    def login(self):
        self.page.goto(self.c.login_url,wait_until='domcontentloaded',timeout=60000)
        self.page.locator('input[name="email"]').fill(self.c.admin_email)
        self.page.locator('input[name="password"]').fill(self.c.admin_password)
        self.page.locator('button[type="submit"]').click();self.page.wait_for_load_state('domcontentloaded',timeout=30000)
        if 'login.php' in self.page.url.lower(): raise RuntimeError('Website login failed.')
    def api(self,action,gw=None):
        params={'action':action,'token':self.c.bot_api_token}
        if gw is not None: params['gameweek']=str(gw)
        r=requests.get(self.c.api_url,params=params,timeout=30);r.raise_for_status();d=r.json()
        if not d.get('success'): raise RuntimeError(d.get('error','Website API error'))
        return d
    def import_sql(self,gw,sql):
        self.page.goto(self.c.admin_url,wait_until='domcontentloaded',timeout=60000)
        self.page.locator('select[name="bulk_gameweek"]').select_option(str(gw))
        self.page.locator('textarea[name="bulk_matches_sql"]').fill(sql)
        if not self.c.import_confirm: raise RuntimeError('IMPORT_CONFIRM is false; import refused.')
        self.page.locator('button[name="bulk_import_matches"]').click();self.page.wait_for_load_state('domcontentloaded',timeout=60000)
        body=self.page.locator('body').inner_text()
        if not re.search(r'imported successfully',body,re.I): raise RuntimeError('Import was not confirmed by myAdmin.php.')
        return body
