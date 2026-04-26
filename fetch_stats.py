#!/usr/bin/env python3
"""
SloPitch Stats Fetcher
Fetches standings and game scores for the VERNON LOCK & SAFE Mixed Division
from the Vernon Coed Slopitch League website and stores them in stats.json.

Run this script any time to update stats.json with new results.
"""

import json
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing dependencies. Run:  pip install requests beautifulsoup4")
    sys.exit(1)

# -- Config ------------------------------------------------------------------
BASE_URL = "https://www.vernoncoedslopitchleague.com/teams/default.asp"
LEAGUE_PARAMS = {"u": "VCSP", "s": "softball"}
TARGET_DIVISION = "VERNON LOCK & SAFE Mixed Division"
MY_TEAM = "BASE INVADERS"
OUTPUT_FILE = Path(__file__).parent / "stats.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
# ----------------------------------------------------------------------------


def fetch_soup(extra_params: dict) -> BeautifulSoup:
    """Fetch a page and return a BeautifulSoup object."""
    params = {**LEAGUE_PARAMS, **extra_params}
    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


# -- Teams --------------------------------------------------------------------

def get_division_teams() -> list[str]:
    """
    Parse the teams page and return the list of teams in TARGET_DIVISION.
    Falls back to the hard-coded list if parsing fails.
    """
    FALLBACK = [
        "BASE INVADERS",
        "THE BLOWOUTS",
        "BAT INTENTIONS",
        "GLOVE HANDLES",
        "BULLSHITTERS",
        "BUNTSMOKERS",
        "HULL RAISER",
    ]

    try:
        soup = fetch_soup({"p": "teams"})
        body_text = soup.get_text(separator="\n")
        lines = [ln.strip() for ln in body_text.splitlines() if ln.strip()]

        # Walk the lines looking for the target division header, then collect
        # team names until the next division header or end of content.
        in_target = False
        teams: list[str] = []
        division_keywords = ("DIVISION", "MIXED", "MONDAY", "LEAGUE")

        for line in lines:
            upper = line.upper()
            is_division_header = any(kw in upper for kw in division_keywords) and len(line) > 6

            if is_division_header:
                if TARGET_DIVISION.upper() in upper:
                    in_target = True
                    continue
                elif in_target:
                    break  # reached the next division
            elif in_target and line and not line.startswith(("http", "©", "Home", "Schedule")):
                teams.append(line.upper())

        return teams if teams else FALLBACK

    except Exception as exc:
        print(f"  Warning: could not parse teams page ({exc}), using fallback list.")
        return FALLBACK


# -- Standings ----------------------------------------------------------------

def get_standings() -> list[dict]:
    """
    Parse the standings page and return rows for TARGET_DIVISION.

    The page uses a flat <table> structure where division headers are
    <tr class="standDiv0"> and team rows are <tr class="standTeam">.
    We walk sibling rows after finding our target division header.
    """
    soup = fetch_soup({"p": "standings"})

    col_names = ["team", "record", "win_pct", "gb", "home", "away",
                 "rf", "ra", "last_10", "streak"]

    # Find the <tr class="standDiv0"> that contains our division name
    target_header = None
    for tr in soup.find_all("tr", class_="standDiv0"):
        if TARGET_DIVISION.upper() in tr.get_text(strip=True).upper():
            target_header = tr
            break

    if not target_header:
        print("  Warning: could not locate Mixed Division standings row.")
        return []

    standings: list[dict] = []
    for sibling in target_header.find_next_siblings("tr"):
        classes = sibling.get("class", [])
        # Stop when we hit the next division header
        if "standDiv0" in classes:
            break
        # Skip header row; collect team rows
        if any(c.startswith("standTeam") for c in classes):
            cells = sibling.find_all("td")
            values = [td.get_text(strip=True) for td in cells]
            if not values or not values[0]:
                continue
            entry = {col: (values[i] if i < len(values) else "") for i, col in enumerate(col_names)}
            standings.append(entry)

    return standings


# -- Scores -------------------------------------------------------------------

def _clean(text: str) -> str:
    """Strip non-printable / non-ASCII junk characters from a string."""
    return re.sub(r"[^\x20-\x7E]", "", text).strip()


def _parse_scoreBoard(board_div) -> dict | None:
    """
    Parse a single <div class='scoreBoard'> into a structured dict.

    Real page structure:
      <div class="gameDate">
        <span>DND 3</span>
        <span>...Apr 17, 2026</span>
        <span>...6:00 PM</span>
      </div>
      <div class="scoreBoardTableWrapper">
        <div class="scoreBoardInnerWrapper">
          <table>
            <thead><tr>
              <td class="location">REGULAR SEASON</td>
              <td class="inn">1</td> ... <td class="inn">7</td>
              <td class="final">R</td>
              <td class="inn">H</td>
              <td class="inn">E</td>
            </tr></thead>
            <tbody>
              <tr class="win"> or <tr>
                <td class="team hasTeamIcon"><img/><div>TEAM NAME</div></td>
                ... innings ... R H E
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div class="scoreSummary">
        <a href="...gameID=XXXXXX...">Box Score and Summary</a>
      </div>
    """
    # ── Header info ────────────────────────────────────────────────────────
    date_div = board_div.find("div", class_="gameDate")
    if not date_div:
        return None

    spans = date_div.find_all("span")
    diamond  = _clean(spans[0].get_text()) if len(spans) > 0 else ""
    date_raw = _clean(spans[1].get_text()) if len(spans) > 1 else ""
    time_raw = _clean(spans[2].get_text()) if len(spans) > 2 else ""

    try:
        game_date = datetime.strptime(date_raw, "%b %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        game_date = date_raw

    # Game type from table header
    location_td = board_div.find("td", class_="location")
    game_type = _clean(location_td.get_text()) if location_td else ""

    # ── Team rows ──────────────────────────────────────────────────────────
    def _int(s: str) -> int:
        s = s.strip()
        return int(s) if s.lstrip("-").isdigit() else 0

    teams_data: list[dict] = []
    tbody = board_div.find("tbody")
    if not tbody:
        return None

    for row in tbody.find_all("tr"):
        # Team name is inside <td class="team"> > <div>
        team_td = row.find("td", class_="team")
        if not team_td:
            continue
        name_div = team_td.find("div")
        name = _clean(name_div.get_text()) if name_div else _clean(team_td.get_text())
        if not name:
            continue

        cells = row.find_all("td")
        # cells[0] = team, cells[1..7] = innings, cells[8] = R, cells[9] = H, cells[10] = E
        innings = [_clean(cells[i].get_text()) for i in range(1, 8) if i < len(cells)]
        runs   = _int(cells[8].get_text()) if len(cells) > 8 else 0
        hits   = _int(cells[9].get_text()) if len(cells) > 9 else 0
        errors = _int(cells[10].get_text()) if len(cells) > 10 else 0
        is_winner = "win" in (row.get("class") or [])

        teams_data.append({"name": name, "innings": innings,
                            "runs": runs, "hits": hits, "errors": errors,
                            "is_winner": is_winner})

    if len(teams_data) < 2:
        return None

    # ── Box score link ─────────────────────────────────────────────────────
    game_id = None
    boxscore_url = None
    link = board_div.find("a", href=re.compile(r"gameID=\d+"))
    if link:
        href = link["href"]
        m = re.search(r"gameID=(\d+)", href)
        if m:
            game_id = m.group(1)
        boxscore_url = (
            href if href.startswith("http")
            else "https://www.vernoncoedslopitchleague.com/teams/" + href.lstrip("/")
        )

    t1, t2 = teams_data[0], teams_data[1]
    if t1["runs"] > t2["runs"]:
        winner = t1["name"]
    elif t2["runs"] > t1["runs"]:
        winner = t2["name"]
    else:
        winner = "TIE"

    return {
        "game_id":       game_id,
        "date":          game_date,
        "time":          time_raw,
        "diamond":       diamond,
        "game_type":     game_type,
        "team1":         t1["name"],
        "team1_runs":    t1["runs"],
        "team1_hits":    t1["hits"],
        "team1_errors":  t1["errors"],
        "team1_innings": t1["innings"],
        "team2":         t2["name"],
        "team2_runs":    t2["runs"],
        "team2_hits":    t2["hits"],
        "team2_errors":  t2["errors"],
        "team2_innings": t2["innings"],
        "winner":        winner,
        "boxscore_url":  boxscore_url,
    }


def get_all_division_scores(division_teams: list[str]) -> list[dict]:
    """
    Walk every page of the scores listing and return only games where at
    least one team belongs to TARGET_DIVISION.
    """
    div_set = {t.upper() for t in division_teams}
    games: list[dict] = []
    seen_ids: set[str] = set()

    def harvest(soup: BeautifulSoup):
        for div in soup.find_all("div", class_="scoreBoard"):
            game = _parse_scoreBoard(div)
            if not game:
                continue
            gid = game["game_id"] or f"{game['date']}_{game['team1']}_{game['team2']}"
            if gid in seen_ids:
                continue
            seen_ids.add(gid)
            if game["team1"].upper() in div_set or game["team2"].upper() in div_set:
                games.append(game)

    def total_pages(soup: BeautifulSoup) -> int:
        # The page uses <span class="pagingSummary"> with text "page X of Y"
        span = soup.find("span", class_="pagingSummary")
        if span:
            m = re.search(r"page\s+\d+\s+of\s+(\d+)", span.get_text(), re.I)
            if m:
                return int(m.group(1))
        # Fallback: search any element
        for tag in soup.find_all(["div", "span", "p"]):
            m = re.search(r"page\s+\d+\s+of\s+(\d+)", tag.get_text(), re.I)
            if m:
                return int(m.group(1))
        return 1

    # Page 1
    soup1 = fetch_soup({"p": "scores"})
    pages = total_pages(soup1)
    harvest(soup1)
    print(f"  Scores: fetching {pages} page(s)...")

    # Remaining pages
    for page_num in range(2, pages + 1):
        soup_n = fetch_soup({
            "p": "scores",
            "pg": str(page_num),
            "pagesize": "10",
            "pageNum": str(page_num),
        })
        harvest(soup_n)

    return sorted(games, key=lambda g: (g["date"], g.get("game_id") or ""))


# -- JSON persistence ---------------------------------------------------------

def load_existing() -> dict:
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save(data: dict):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    print(f"  Saved -> {OUTPUT_FILE}")


# -- Main ---------------------------------------------------------------------

def main():
    print(f"Fetching stats for: {TARGET_DIVISION}")
    print(f"My team: {MY_TEAM}\n")

    # 1. Division teams
    print("Step 1/3  Getting division teams...")
    division_teams = get_division_teams()
    print(f"  Teams: {', '.join(division_teams)}")

    # 2. Standings
    print("Step 2/3  Fetching standings...")
    standings = get_standings()
    if standings:
        print(f"  {len(standings)} teams in standings.")
    else:
        print("  No standings data found.")

    # 3. Scores
    print("Step 3/3  Fetching all game scores...")
    fresh_games = get_all_division_scores(division_teams)

    # Merge with existing data (keep any games not returned this run)
    existing = load_existing()
    existing_by_id: dict[str, dict] = {
        g.get("game_id") or f"{g['date']}_{g['team1']}_{g['team2']}": g
        for g in existing.get("games", [])
    }
    # Secondary index: fallback key → primary key, to remove stale fallback entries
    fallback_to_id: dict[str, str] = {
        f"{g['date']}_{g['team1']}_{g['team2']}": (g.get("game_id") or f"{g['date']}_{g['team1']}_{g['team2']}")
        for g in existing.get("games", [])
    }
    for game in fresh_games:
        gid = game.get("game_id") or f"{game['date']}_{game['team1']}_{game['team2']}"
        fallback = f"{game['date']}_{game['team1']}_{game['team2']}"
        # If a real game_id is now available, remove any stale fallback-keyed entry
        if game.get("game_id") and fallback in fallback_to_id:
            stale_key = fallback_to_id[fallback]
            if stale_key != gid:
                existing_by_id.pop(stale_key, None)
        existing_by_id[gid] = game  # overwrite/add

    merged_games = sorted(existing_by_id.values(), key=lambda g: (g["date"], g.get("game_id") or ""))
    new_count = len(merged_games) - len(existing.get("games", []))

    data = {
        "division":     TARGET_DIVISION,
        "my_team":      MY_TEAM,
        "last_updated": datetime.now(ZoneInfo("America/Vancouver")).isoformat(timespec="seconds"),
        "standings":    standings,
        "games":        merged_games,
    }

    save(data)

    # -- Pretty summary ----------------------------------------------------
    print()
    print(f"{'-'*65}")
    print(f"  {TARGET_DIVISION}")
    print(f"{'-'*65}")
    print(f"  {'Team':<25} {'Record':<10} {'W%':<7} {'GB':<6} {'RF':>4} {'RA':>4}  Streak")
    print(f"  {'-'*60}")
    for row in standings:
        marker = "  << you" if row["team"].upper() == MY_TEAM else ""
        print(
            f"  {row['team']:<25} {row['record']:<10} {row['win_pct']:<7} "
            f"{row['gb']:<6} {row['rf']:>4} {row['ra']:>4}  {row['streak']}{marker}"
        )

    print()
    print(f"  Division games  ({len(merged_games)} total, {max(new_count, 0)} new this run)")
    print(f"  {'-'*60}")
    for g in merged_games:
        result = f"{g['team1']} {g['team1_runs']}-{g['team2_runs']} {g['team2']}"
        flag = ""
        if g["team1"].upper() == MY_TEAM or g["team2"].upper() == MY_TEAM:
            flag = "  << my game"
        print(f"  {g['date']}  {result}{flag}")

    print(f"{'-'*65}")
    print()


if __name__ == "__main__":
    main()
