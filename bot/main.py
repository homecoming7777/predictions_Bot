import argparse,json
from datetime import datetime,timezone
from .config import load_config
from .fpl_client import FPLClient
from .fixtures import normalize,validate
from .sql_generator import generate,save
from .site import Site

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--execute',action='store_true');a=ap.parse_args();c=load_config();dry=not a.execute
    result={'started_at':datetime.now(timezone.utc).isoformat(),'mode':'PREVIEW' if dry else 'EXECUTE','status':'FAILED'}
    try:
        with Site(c) as site:
            site.login(); status=site.api('status'); latest=status.get('latest_gameweek')
            result['website_latest_gameweek']=latest; target=int(latest)+1 if latest else 1
            if target>38: result.update(status='STOPPED',message='Season complete: website is already at GW38.');print(json.dumps(result,indent=2));return 0
            result['target_gameweek']=target
            exists=site.api('exists',target)['exists']
            if exists: result.update(status='STOPPED',message=f'GW{target} already exists; no changes made.');print(json.dumps(result,indent=2));return 0
        fpl=FPLClient();boot=fpl.bootstrap();teams={int(t['id']):t['name'] for t in boot['teams']};raw=fpl.fixtures(target);result['fpl_fixtures_retrieved']=len(raw)
        fs=normalize(raw,teams,c.site_timezone,target);validate(fs,target);result['validated_fixtures']=len(fs)
        sql=generate(fs);path=save(sql,target);result['sql_file']=str(path)
        if dry: result.update(status='SUCCESS - PREVIEW',message='Preview only; website was not modified.');print(json.dumps(result,indent=2));return 0
        with Site(c) as site:
            site.login();
            if site.api('exists',target)['exists']: raise RuntimeError('Target GW appeared before import; cancelled.')
            result['import_response']=site.import_sql(target,sql)[-1200:]
            v=site.api('verify',target)
            result['verification']=v
            if not v.get('verified'): raise RuntimeError('Post-import verification failed.')
        result.update(status='SUCCESS - VERIFIED',message=f'GW{target} imported and verified.');print(json.dumps(result,indent=2));return 0
    except Exception as e:
        result['error']=f'{type(e).__name__}: {e}';print(json.dumps(result,indent=2));return 1
if __name__=='__main__': raise SystemExit(main())
