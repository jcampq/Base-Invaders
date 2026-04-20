#!/usr/bin/env python3
"""
SloPitch Schedule Fetcher
Fetches the full BASE INVADERS game schedule from the Vernon Coed Slopitch
League website and stores it in schedule.json.

Run this script any time to refresh schedule.json with updated scores/results.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing dependencies. Run:  pip install requests beautifulsoup4")
    sys.exit(1)

# -- Config ------------------------------------------------------------------
BASE_URL   = "https://www.vernoncoedslopitchleague.com/teams/default.asp"
SCHEDULE_URL_PARAMS = {"u": "VCSP", "s": "softball", "p": "schedule", "div": "952569"}
MY_TEAM    = "BASE INVADERS"
OUTPUT_FILE = Path(__file__).parent / "schedule.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
# ----------------------------------------------------------------------------

# Maps short date format "M/D/YY" -> "YYYY-MM-DD"
def _parse_date(raw: str) -> str:
    """Convert 'Thu, 4/16/26' to '2026-04-16'."""
    raw = raw.strip()
    # Strip leading day-of-week if present (e.g. "Thu, ")
    if "," in raw:
        raw = raw.split(",", 1)[1].strip()
    try:
        return datetime.strptime(raw, "%m/%d/%y").strftime("%Y-%m-%d")
    except ValueError:
        return raw


def _parse_score(score_text: str) -> dict:
    """
    Parse a score cell like 'W 15 - 8', 'L 5 - 12', 'T 19 - 19', or ''.

    Returns a dict with keys: result, my_runs, opponent_runs.
    result is 'WIN', 'LOSS', 'TIE', or None for unplayed games.
    """
    text = score_text.strip()
    if not text:
        return {"result": None, "my_runs": None, "opponent_runs": None}

    m = re.match(r"^([WLT])\s+(\d+)\s*-\s*(\d+)$", text, re.I)
    if m:
        letter = m.group(1).upper()
        result_map = {"W": "WIN", "L": "LOSS", "T": "TIE"}
        return {
            "result":        result_map.get(letter, letter),
            "my_runs":       int(m.group(2)),
            "opponent_runs": int(m.group(3)),
        }

    # Unexpected format - keep raw
    return {"result": text, "my_runs": None, "opponent_runs": None}


def fetch_schedule() -> list[dict]:
    """Fetch and parse the full schedule table."""
    resp = requests.get(BASE_URL, params=SCHEDULE_URL_PARAMS, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    table = soup.find("table", class_="scheduleList")
    if not table:
        raise RuntimeError("Could not find scheduleList table on the page.")

    games: list[dict] = []

    for row in table.find_all("tr"):
        classes = row.get("class", [])
        # Only process actual game rows (skip month headers and table header)
        if "schedRow" not in classes:
            continue

        row_id = row.get("id", "")  # e.g. "schedRow2031535"
        game_id = row_id.replace("schedRow", "") if row_id else None

        def cell(cls: str) -> str:
            td = row.find("td", class_=cls)
            return td.get_text(" ", strip=True).replace("\xa0", " ") if td else ""

        date_raw     = cell("col_Date")   # "Thu, 4/16/26"
        time_raw     = cell("col_Time")   # "6:00 pm"
        opponent_raw = cell("col_Opponent")  # "BAT INTENTIONS" or "@ BAT INTENTIONS"
        score_raw    = cell("col_Score")  # "T 19 - 19" or ""
        location     = cell("col_Location")  # "DND 8"
        details_type = cell("col_Details")   # "Box Score" or "Game Info"

        # Day of week from date string
        day_of_week = date_raw.split(",")[0].strip() if "," in date_raw else ""

        # Home / away: away games have opponent prefixed with "@"
        if opponent_raw.startswith("@"):
            home_away = "away"
            opponent  = opponent_raw.lstrip("@ ").strip()
        else:
            home_away = "home"
            opponent  = opponent_raw.strip()

        # Date
        game_date = _parse_date(date_raw)

        # Score / result
        score_info = _parse_score(score_raw)
        status = "completed" if score_info["result"] is not None else "scheduled"

        # Details link (box score or preview)
        details_link_tag = row.find("a")
        details_url = None
        if details_link_tag:
            href = details_link_tag.get("href", "")
            details_url = (
                href if href.startswith("http")
                else "https://www.vernoncoedslopitchleague.com/teams/" + href.lstrip("/")
            )

        games.append({
            "game_id":       game_id,
            "date":          game_date,
            "day_of_week":   day_of_week,
            "time":          time_raw,
            "home_away":     home_away,
            "opponent":      opponent,
            "location":      location,
            "status":        status,
            "result":        score_info["result"],
            "my_runs":       score_info["my_runs"],
            "opponent_runs": score_info["opponent_runs"],
            "details_type":  details_type,
            "details_url":   details_url,
        })

    return games


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
        "last_updated": datetime.now().isoformat(timespec="seconds"),
        "record": {
            "wins":   wins,
            "losses": losses,
            "ties":   ties,
        },
        "games": games,
    }

    save(data)

    # -- Pretty summary -------------------------------------------------------
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
        ha = g["home_away"][0].upper()  # H or A
        print(
            f"  {g['date']:<12} {g['day_of_week']:<5} {g['time']:<9} "
            f"{ha:<5} {g['opponent']:<22} {score_str:<12} {g['location']}"
        )
    print(f"{'-'*68}")
    print()


if __name__ == "__main__":
    main()
