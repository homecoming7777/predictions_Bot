from datetime import datetime
from zoneinfo import ZoneInfo

def kickoff(value,tz):
    dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None: raise ValueError(f'Non timezone-aware kickoff: {value}')
    return dt.astimezone(ZoneInfo(tz)).strftime('%Y-%m-%d %H:%M:%S')

def normalize(raw,teams,timezone,gw):
    out=[]
    for x in raw:
        if int(x.get('event') or 0)!=gw: raise RuntimeError(f'Fixture event mismatch: {x.get("event")} != {gw}')
        h,a=int(x['team_h']),int(x['team_a'])
        if h not in teams or a not in teams: raise RuntimeError('Unknown FPL team id')
        out.append({'fpl_id':int(x['id']),'gameweek':gw,'home_team':teams[h],'away_team':teams[a], 'match_date':kickoff(x['kickoff_time'],timezone)})
    return sorted(out,key=lambda x:x['match_date'])

def validate(fs,gw):
    if len(fs)!=10: raise RuntimeError(f'Safety stop: FPL returned {len(fs)} fixtures for GW {gw}; expected 10.')
    seen=set()
    for f in fs:
        k=(f['home_team'],f['away_team'],f['match_date'])
        if f['home_team']==f['away_team'] or k in seen: raise RuntimeError(f'Invalid/duplicate fixture: {k}')
        seen.add(k)
