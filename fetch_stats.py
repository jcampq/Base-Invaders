#!/usr/bin/env python3
"""
SloPitch Stats Fetcher
Fetches standings and game scores for the VERNON LOCK & SAFE Mixed Division
from the division schedule page and stores them in stats.json.
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
BASE_URL         = "https://www.vernoncoedslopitchleague.com/teams/default.asp"
LEAGUE_PARAMS    = {"u": "VCSP", "s": "softball"}
DIVISION_PARAMS  = {"u": "VCSP", "s": "softball", "p": "schedule", "div": "1014671"}
TARGET_DIVISION  = "VERNON LOCK & SAFE Mixed Division"
MY_TEAM          = "BASE INVADERS"
OUTPUT_FILE      = Path(__file__).parent / "stats.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
# ----------------------------------------------------------------------------


def fetch_soup(params: dict) -> BeautifulSoup:
    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def _clean(text: str) -> str:
    return re.sub(r"[^\x20-\x7E]", "", text).strip()


def _parse_date(raw: str) -> str | None:
    """Convert 'Thu, 4/16/26' or 'Thursday, April 16, 2026' to '2026-04-16'."""
    raw = raw.strip()
    # Long form with month name: strip leading day-of-week if present
    if "," in raw and "/" not in raw:
        raw = raw.split(",", 1)[1].strip()
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    # Short form: "Thu, 4/16/26"
    if "," in raw:
        raw = raw.split(",", 1)[1].strip()
    try:
        return datetime.strptime(raw, "%m/%d/%y").strftime("%Y-%m-%d")
    except ValueError:
        return None


# -- Standings ----------------------------------------------------------------

def get_standings() -> list[dict]:
    soup = fetch_soup({**LEAGUE_PARAMS, "p": "standings"})
    col_names = ["team", "record", "win_pct", "gb", "home", "away",
                 "rf", "ra", "last_10", "streak"]

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
        if "standDiv0" in classes:
            break
        if any(c.startswith("standTeam") for c in classes):
            cells = sibling.find_all("td")
            values = [td.get_text(strip=True) for td in cells]
            if not values or not values[0]:
                continue
            entry = {col: (values[i] if i < len(values) else "") for i, col in enumerate(col_names)}
            standings.append(entry)

    return standings


# -- Games from division schedule ---------------------------------------------

def get_division_games() -> list[dict]:
    """
    Fetch all completed games from the division schedule page.
    Each game has exactly one row with a unique game_id — no duplicates possible.
    """
    soup = fetch_soup(DIVISION_PARAMS)
    table = soup.find("table", class_="scheduleList")
    if not table:
        raise RuntimeError("Could not find scheduleList table on the division schedule page.")

    games: list[dict] = []
    current_date = None

    for row in table.find_all("tr"):
        row_id = row.get("id", "")

        if not row_id.startswith("schedRow"):
            # Look for date in header rows ("Thursday, April 16, 2026")
            row_text = row.get_text(" ", strip=True)
            m = re.search(
                r'\b(?:January|February|March|April|May|June|July|August|'
                r'September|October|November|December)\s+\d+,\s+\d{4}\b',
                row_text
            )
            if m:
                try:
                    current_date = datetime.strptime(m.group(0), "%B %d, %Y").strftime("%Y-%m-%d")
                except ValueError:
                    pass
            # Also check for col_Date cell in case the table has per-row dates
            date_cell = row.find("td", class_="col_Date")
            if date_cell:
                parsed = _parse_date(date_cell.get_text(" ", strip=True).replace("\xa0", " "))
                if parsed:
                    current_date = parsed
            continue

        game_id = row_id.replace("schedRow", "")

        # Per-row date overrides tracked date if present
        date_cell = row.find("td", class_="col_Date")
        if date_cell:
            parsed = _parse_date(date_cell.get_text(" ", strip=True).replace("\xa0", " "))
            if parsed:
                current_date = parsed
        if not current_date:
            continue

        # Time and location
        time_cell = row.find("td", class_="col_Time")
        time_raw  = time_cell.get_text(strip=True) if time_cell else ""
        loc_cell  = row.find("td", class_="col_Location")
        location  = _clean(loc_cell.get_text()) if loc_cell else ""

        # Team links: first = home, second = away
        team_links = row.find_all("a", href=re.compile(r"gameID="))
        if len(team_links) < 2:
            continue

        home_team = _clean(team_links[0].get_text())
        away_team = _clean(team_links[1].get_text())

        # Completed games have "boxscore" in the link; upcoming have "preview"
        first_href = team_links[0].get("href", "")
        if "boxscore" not in first_href:
            continue  # stats.json only tracks completed games

        boxscore_url = (
            first_href if first_href.startswith("http")
            else "https://www.vernoncoedslopitchleague.com/teams/" + first_href.lstrip("/")
        )

        # Scores: cells whose entire text is digits + W/L/T (e.g. "20W", "8L", "19T")
        score_cells = [
            c.get_text(strip=True)
            for c in row.find_all("td")
            if re.match(r'^\d+[WLT]$', c.get_text(strip=True), re.I)
        ]
        if len(score_cells) < 2:
            continue

        home_runs = int(score_cells[0][:-1])
        away_runs = int(score_cells[1][:-1])
        if home_runs > away_runs:
            winner = home_team
        elif away_runs > home_runs:
            winner = away_team
        else:
            winner = "TIE"

        games.append({
            "game_id":     game_id,
            "date":        current_date,
            "time":        time_raw,
            "diamond":     location,
            "team1":       home_team,
            "team1_runs":  home_runs,
            "team2":       away_team,
            "team2_runs":  away_runs,
            "winner":      winner,
            "boxscore_url": boxscore_url,
        })

    return sorted(games, key=lambda g: (g["date"], g["game_id"]))


# -- JSON persistence ---------------------------------------------------------

def save(data: dict):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    print(f"  Saved -> {OUTPUT_FILE}")


# -- Main ---------------------------------------------------------------------

def main():
    print(f"Fetching stats for: {TARGET_DIVISION}")
    print(f"My team: {MY_TEAM}\n")

    print("Step 1/2  Fetching standings...")
    standings = get_standings()
    if standings:
        print(f"  {len(standings)} teams in standings.")
    else:
        print("  No standings data found.")

    print("Step 2/2  Fetching division game results...")
    games = get_division_games()
    print(f"  {len(games)} completed games found.")

    data = {
        "division":     TARGET_DIVISION,
        "my_team":      MY_TEAM,
        "last_updated": datetime.now(ZoneInfo("America/Vancouver")).isoformat(timespec="seconds"),
        "standings":    standings,
        "games":        games,
    }

    save(data)

    # -- Pretty summary -------------------------------------------------------
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
    print(f"  Division games  ({len(games)} total)")
    print(f"  {'-'*60}")
    for g in games:
        result = f"{g['team1']} {g['team1_runs']}-{g['team2_runs']} {g['team2']}"
        flag   = "  << my game" if g["team1"].upper() == MY_TEAM or g["team2"].upper() == MY_TEAM else ""
        print(f"  {g['date']}  {result}{flag}")

    print(f"{'-'*65}")
    print()


if __name__ == "__main__":
    main()
