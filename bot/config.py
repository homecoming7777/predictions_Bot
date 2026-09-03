from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv()

def env_bool(name, default=False):
    v=os.getenv(name)
    return default if v is None else v.strip().lower() in {'1','true','yes','on'}

@dataclass(frozen=True)
class Config:
    website_url: str
    admin_email: str
    admin_password: str
    login_path: str
    admin_path: str
    site_api_path: str
    bot_api_token: str
    site_timezone: str
    headless: bool
    import_confirm: bool
    @property
    def login_url(self): return self.website_url.rstrip('/')+'/'+self.login_path.lstrip('/')
    @property
    def admin_url(self): return self.website_url.rstrip('/')+'/'+self.admin_path.lstrip('/')
    @property
    def api_url(self): return self.website_url.rstrip('/')+'/'+self.site_api_path.lstrip('/')

def load_config():
    c=Config(
        os.getenv('WEBSITE_URL','').strip(), os.getenv('ADMIN_EMAIL','').strip(), os.getenv('ADMIN_PASSWORD',''),
        os.getenv('ADMIN_LOGIN_PATH','/login.php'), os.getenv('ADMIN_PAGE_PATH','/myAdmin.php'),
        os.getenv('BOT_API_PATH','/bot_api.php'), os.getenv('BOT_API_TOKEN',''),
        os.getenv('SITE_TIMEZONE','Africa/Casablanca'), env_bool('HEADLESS',True), env_bool('IMPORT_CONFIRM',False))
    if not c.website_url: raise ValueError('WEBSITE_URL is required.')
    if not c.admin_email or not c.admin_password: raise ValueError('ADMIN_EMAIL and ADMIN_PASSWORD are required.')
    if not c.bot_api_token: raise ValueError('BOT_API_TOKEN is required.')
    return c
