#!/usr/bin/env python3
"""
SloPitch Schedule Fetcher
Fetches BASE INVADERS games from the division schedule page and stores
them in schedule.json.
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
BASE_URL        = "https://www.vernoncoedslopitchleague.com/teams/default.asp"
DIVISION_PARAMS = {"u": "VCSP", "s": "softball", "p": "schedule", "div": "1014671"}
MY_TEAM         = "BASE INVADERS"
OUTPUT_FILE     = Path(__file__).parent / "schedule.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
# ----------------------------------------------------------------------------


def _clean(text: str) -> str:
    return re.sub(r"[^\x20-\x7E]", "", text).strip()


def _parse_date(raw: str) -> str | None:
    """Convert 'Thu, 4/16/26' or 'Thursday, April 16, 2026' to '2026-04-16'."""
    raw = raw.strip()
    if "," in raw and "/" not in raw:
        raw = raw.split(",", 1)[1].strip()
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    if "," in raw:
        raw = raw.split(",", 1)[1].strip()
    try:
        return datetime.strptime(raw, "%m/%d/%y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def fetch_schedule() -> list[dict]:
    """
    Fetch all BASE INVADERS games from the division schedule page.
    Home team is always listed first in each row; away team second.
    """
    resp = requests.get(BASE_URL, params=DIVISION_PARAMS, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    table = soup.find("table", class_="scheduleList")
    if not table:
        raise RuntimeError("Could not find scheduleList table on the division schedule page.")

    games: list[dict] = []
    current_date = None

    for row in table.find_all("tr"):
        row_id = row.get("id", "")

        if not row_id.startswith("schedRow"):
            # Track date from header rows ("Thursday, April 16, 2026")
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
            date_cell = row.find("td", class_="col_Date")
            if date_cell:
                parsed = _parse_date(date_cell.get_text(" ", strip=True).replace("\xa0", " "))
                if parsed:
                    current_date = parsed
            continue

        game_id = row_id.replace("schedRow", "")

        # Per-row date
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

        home_team = _clean(team_links[0].get_text()).upper()
        away_team = _clean(team_links[1].get_text()).upper()

        # Only BASE INVADERS games
        if home_team != MY_TEAM and away_team != MY_TEAM:
            continue

        home_away = "home" if home_team == MY_TEAM else "away"
        opponent  = away_team if home_away == "home" else home_team

        # Status and details URL
        first_href   = team_links[0].get("href", "")
        is_completed = "boxscore" in first_href
        status       = "completed" if is_completed else "scheduled"
        details_url  = (
            first_href if first_href.startswith("http")
            else "https://www.vernoncoedslopitchleague.com/teams/" + first_href.lstrip("/")
        )

        # Scores: cells whose entire text is digits + W/L/T (e.g. "20W", "8L", "19T")
        result = my_runs = opponent_runs = None
        if is_completed:
            score_cells = [
                c.get_text(strip=True)
                for c in row.find_all("td")
                if re.match(r'^\d+[WLT]$', c.get_text(strip=True), re.I)
            ]
            if len(score_cells) >= 2:
                home_runs     = int(score_cells[0][:-1])
                away_runs     = int(score_cells[1][:-1])
                my_runs       = home_runs if home_away == "home" else away_runs
                opponent_runs = away_runs if home_away == "home" else home_runs
                if my_runs > opponent_runs:
                    result = "WIN"
                elif opponent_runs > my_runs:
                    result = "LOSS"
                else:
                    result = "TIE"

        try:
            day_of_week = datetime.strptime(current_date, "%Y-%m-%d").strftime("%a")
        except ValueError:
            day_of_week = ""

        games.append({
            "game_id":      game_id,
            "date":         current_date,
            "day_of_week":  day_of_week,
            "time":         time_raw,
            "home_away":    home_away,
            "opponent":     opponent,
            "location":     location,
            "status":       status,
            "result":       result,
            "my_runs":      my_runs,
            "opponent_runs": opponent_runs,
            "details_url":  details_url,
        })

    return sorted(games, key=lambda g: (g["date"], g["game_id"]))


def save(data: dict):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    print(f"  Saved -> {OUTPUT_FILE}")


def main():
    print(f"Fetching schedule for: {MY_TEAM}\n")

    games = fetch_schedule()

    completed = [g for g in games if g["status"] == "completed"]
    scheduled = [g for g in games if g["status"] == "scheduled"]

    wins   = sum(1 for g in completed if g["result"] == "WIN")
    losses = sum(1 for g in completed if g["result"] == "LOSS")
    ties   = sum(1 for g in completed if g["result"] == "TIE")

    data = {
        "team":         MY_TEAM,
        "last_updated": datetime.now(ZoneInfo("America/Vancouver")).isoformat(timespec="seconds"),
        "record": {
            "wins":   wins,
            "losses": losses,
            "ties":   ties,
        },
        "games": games,
    }

    save(data)

    print()
    print(f"{'-'*68}")
    print(f"  {MY_TEAM} - Spring 2026 Schedule")
    print(f"  Record: {wins}W - {losses}L - {ties}T  |  "
          f"{len(completed)} played, {len(scheduled)} remaining")
    print(f"{'-'*68}")
    print(f"  {'Date':<12} {'Day':<5} {'Time':<9} {'H/A':<5} {'Opponent':<22} {'Score':<12} Loc")
    print(f"  {'-'*63}")
    for g in games:
        score_str = (
            f"{g['result']} {g['my_runs']}-{g['opponent_runs']}"
            if g["result"] else "-"
        )
        ha = g["home_away"][0].upper()
        print(
            f"  {g['date']:<12} {g['day_of_week']:<5} {g['time']:<9} "
            f"{ha:<5} {g['opponent']:<22} {score_str:<12} {g['location']}"
        )
    print(f"{'-'*68}")
    print()


if __name__ == "__main__":
    main()
