from bot.fixtures import normalize
from bot.sql_generator import generate

def test_fixture_and_sql():
    raw=[{'id':1,'event':6,'team_h':1,'team_a':2,'kickoff_time':'2026-09-05T15:00:00Z'}]
    fs=normalize(raw,{1:'Arsenal',2:'Liverpool'},'Africa/Casablanca',6)
    s=generate(fs)
    assert "'Arsenal'" in s and "'Liverpool'" in s and ',\n    NULL,\n    NULL,\n    6,\n    NULL' in s
