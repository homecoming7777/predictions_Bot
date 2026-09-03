from pathlib import Path


def q(s):
    return "'" + str(s).replace("\\", "\\\\").replace("'", "''") + "'"


# FPL team name -> your database/team logo filename
TEAM_LOGOS = {
    "Arsenal": "/PL_Teams/arsenal.png",
    "Aston Villa": "/PL_Teams/aston-villa.png",
    "Bournemouth": "/PL_Teams/bournemouth.png",
    "Brentford": "/PL_Teams/brentford.png",
    "Brighton": "/PL_Teams/brighton.png",
    "Chelsea": "/PL_Teams/chelsea.png",
    "Coventry City": "/PL_Teams/coventry-city.png",
    "Crystal Palace": "/PL_Teams/crystal-palace.png",
    "Everton": "/PL_Teams/everton.png",
    "Fulham": "/PL_Teams/fulham.png",
    "Hull City": "/PL_Teams/hull-city.png",
    "Ipswich Town": "/PL_Teams/ipswich-town.png",
    "Liverpool": "/PL_Teams/liverpool.png",
    "Man City": "/PL_Teams/manchester-city.png",
    "Man Utd": "/PL_Teams/manchester-united.png",
    "Manchester City": "/PL_Teams/manchester-city.png",
    "Manchester United": "/PL_Teams/manchester-united.png",
    "Nott'm Forest": "/PL_Teams/nottingham-forest.png",
    "Nottingham Forest": "/PL_Teams/nottingham-forest.png",
    "Spurs": "/PL_Teams/tottenham.png",
    "Tottenham Hotspur": "/PL_Teams/tottenham.png",
    "Sunderland": "/PL_Teams/sunderland.png",
    "Leeds": "/PL_Teams/leeds.png",
    "Newcastle": "/PL_Teams/newcastle.png",
}


def logo_for(team):
    team = str(team).strip()

    if team in TEAM_LOGOS:
        return TEAM_LOGOS[team]

    raise ValueError(
        f"No logo mapping found for team: {team!r}. "
        "Add this team to TEAM_LOGOS in bot/sql_generator.py."
    )


def generate(fs):
    if not fs:
        raise ValueError("No fixtures")

    vals = []

    for f in fs:
        home_team = f["home_team"]
        away_team = f["away_team"]

        home_logo = logo_for(home_team)
        away_logo = logo_for(away_team)

        vals.append(
            "(\n"
            f"    {q(home_team)},\n"
            f"    {q(home_logo)},\n"
            f"    {q(away_team)},\n"
            f"    {q(away_logo)},\n"
            f"    {q(f['match_date'])},\n"
            "    NULL,\n"
            "    NULL,\n"
            f"    {int(f['gameweek'])},\n"
            "    NULL,\n"
            "    'Premier League'\n"
            ")"
        )

    return (
        "INSERT INTO matches "
        "(home_team, home_team_pic, away_team, away_team_pic, match_date, "
        "home_score, away_score, gameweek, deadline, competition)\n"
        "VALUES\n"
        + ",\n".join(vals)
        + ";\n"
    )


def save(sql, gw):
    p = Path("sql")
    p.mkdir(exist_ok=True)

    f = p / f"gameweek_{gw}.sql"
    f.write_text(sql, encoding="utf8")

    return f