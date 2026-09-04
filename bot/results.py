"""
Match-result reconciliation.

Pure functions only (no network, no browser) so they stay easy to unit test,
matching the style of fixtures.py in this project.
"""


def pending_matches(matches):
    """
    Site matches (as returned by bot_api.php's `matches` action) that do not
    yet have a result recorded.
    """
    return [
        m for m in matches
        if m.get('home_score') is None or m.get('away_score') is None
    ]


def build_fpl_results_index(raw_fixtures, teams):
    """
    Index FPL's /fixtures/?event=N response by (home_team_name, away_team_name)
    so a site match row can be looked up by team names alone.

    `teams` is the FPL team id -> name map from bootstrap-static, the same
    map used when the fixtures were first generated, so the names line up
    exactly with what is stored in the `matches` table.
    """
    index = {}

    for fx in raw_fixtures:
        home_id = fx.get('team_h')
        away_id = fx.get('team_a')

        if home_id is None or away_id is None:
            continue

        home_name = teams.get(int(home_id))
        away_name = teams.get(int(away_id))

        if home_name is None or away_name is None:
            continue

        index[(home_name, away_name)] = {
            'finished': bool(fx.get('finished')),
            'home_score': fx.get('team_h_score'),
            'away_score': fx.get('team_a_score'),
        }

    return index


def finished_updates(pending, fpl_index):
    """
    For each pending site match, check whether FPL has a finished score for
    it. Matches FPL has not finished yet (or cannot be matched by team name)
    are simply left out - they stay pending for the next run.

    Returns a list of dicts:
        {'match_id', 'home_team', 'away_team', 'home_score', 'away_score'}
    """
    updates = []

    for m in pending:
        fpl_result = fpl_index.get((m['home_team'], m['away_team']))

        if fpl_result is None or not fpl_result['finished']:
            continue

        if fpl_result['home_score'] is None or fpl_result['away_score'] is None:
            continue

        updates.append({
            'match_id': m['id'],
            'home_team': m['home_team'],
            'away_team': m['away_team'],
            'home_score': int(fpl_result['home_score']),
            'away_score': int(fpl_result['away_score']),
        })

    return updates