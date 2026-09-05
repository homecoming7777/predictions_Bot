import requests
BASE='https://fantasy.premierleague.com/api'
class FPLClient:
    def __init__(self):
        self.s=requests.Session(); self.s.headers.update({'User-Agent':'FPL-Fixture-Bot/1.0','Accept':'application/json'})
    def get(self,path):
        r=self.s.get(BASE+path,timeout=30); r.raise_for_status(); return r.json()
    def bootstrap(self): return self.get('/bootstrap-static/')
    def fixtures(self,gw): return self.get(f'/fixtures/?event={gw}')
    def fixtures_all(self): return self.get('/fixtures/')


def team_names(bootstrap):
    """FPL team id -> team name map, built from a bootstrap() response."""
    return {int(team['id']): team['name'] for team in bootstrap['teams']}