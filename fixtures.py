
import os
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
import yaml
from icalendar import Calendar, Event, Alarm

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "calendars"
CONFIG_FILE = BASE_DIR / "config.yml"
RIYADH = ZoneInfo("Asia/Riyadh")

API_URL = "https://api.api-ninjas.com/v1/soccermatches"
API_KEY = os.environ.get("API_NINJAS_KEY")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("football-calendar")

# المسابقات التي توثق API Ninjas إتاحتها في الخطة المجانية
LEAGUE_CODES = {
    "Premier League": "epl",
    "La Liga": "laliga",
    "Serie A": "seriea",
    "Bundesliga": "bundesliga",
    "Ligue 1": "ligue1",
    "UEFA Champions League": "ucl",
    "UEFA Europa League": "uel",
    "UEFA Conference League": "uecl",
    "MLS": "mls",
}

def load_config():
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)

def new_calendar(name):
    cal = Calendar()
    cal.add("prodid", "-//Football Fixtures Saudi//AR")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", name)
    cal.add("x-wr-timezone", "Asia/Riyadh")
    return cal

def api_request(league, season, offset):
    if not API_KEY:
        raise RuntimeError("Missing API_NINJAS_KEY secret")

    response = requests.get(
        API_URL,
        headers={"X-Api-Key": API_KEY},
        params={
            "league": league,
            "season": season,
            "offset": offset
        },
        timeout=45
    )

    response.raise_for_status()
    data = response.json()

    if isinstance(data, dict):
        raise RuntimeError(str(data))

    return data

def get_matches(league, season):
    matches = []
    offset = 0

    while True:
        batch = api_request(league, season, offset)
        matches.extend(batch)

        if len(batch) < 50:
            break

        offset += 50

    return matches

def add_match(cal, match):
    start = match.get("start_time")
    if not start:
        return

    kickoff = datetime.fromisoformat(
        start.replace("Z", "+00:00")
    ).astimezone(RIYADH)

    home = match.get("home_team", {}).get("name", "Home")
    away = match.get("away_team", {}).get("name", "Away")
    league = match.get("league", "Football")
    status = match.get("status", "scheduled")

    home_score = match.get("home_score")
    away_score = match.get("away_score")

    score = ""
    if home_score is not None and away_score is not None:
        score = f" | {home_score} - {away_score}"

    game_id = match.get("game_id")
    if not game_id:
        return

    event = Event()
    event.add("uid", f"{game_id}@football-fixtures-saudi")
    event.add("summary", f"{home} vs {away}{score}")
    event.add("dtstart", kickoff)
    event.add("dtend", kickoff + timedelta(hours=2))
    event.add("dtstamp", datetime.now(timezone.utc))

    venue = match.get("venue") or {}
    event.add("location", venue.get("name") or "")

    description = [
        f"Competition: {league}",
        f"Home: {home}",
        f"Away: {away}",
        f"Saudi time: {kickoff:%Y-%m-%d %H:%M}",
        f"Status: {status}",
        f"Score: {score or 'Not available'}",
        f"Venue: {venue.get('name') or 'Not announced'}",
        "Broadcast: Not available"
    ]

    event.add("description", "\n".join(description))
    event.add("status", "CANCELLED" if status == "canceled" else "CONFIRMED")

    alarm = Alarm()
    alarm.add("action", "DISPLAY")
    alarm.add("description", f"Match starting: {home} vs {away}")
    alarm.add("trigger", timedelta(minutes=-30))
    event.add_component(alarm)

    cal.add_component(event)

def main():
    if not API_KEY:
        raise RuntimeError("API_NINJAS_KEY is not configured")

    config = load_config()
    season = int(config.get("season", datetime.now().year))

    OUTPUT_DIR.mkdir(exist_ok=True)

    calendars = {
        "all": new_calendar("Football Fixtures - All"),
        "europe": new_calendar("Football Fixtures - Europe"),
        "uefa": new_calendar("Football Fixtures - UEFA"),
    }

    total = 0

    for item in config.get("leagues", []):
        name = item["name"]
        code = LEAGUE_CODES.get(name)

        if not code:
            log.warning("%s: not included in the initial free-plan test", name)
            continue

        group = item.get("group", "europe")

        try:
            matches = get_matches(code, season)
            added = 0

            for match in matches:
                add_match(calendars["all"], match)

                if group in calendars:
                    add_match(calendars[group], match)

                added += 1

            total += added
            log.info("%s (%s): %s matches", name, code, added)

        except Exception as exc:
            log.exception("Failed to update %s: %s", name, exc)

    if total == 0:
        raise RuntimeError(
            "No matches retrieved. Check API key, plan and API response."
        )

    for name, cal in calendars.items():
        path = OUTPUT_DIR / f"{name}.ics"
        path.write_bytes(cal.to_ical())
        log.info("Created %s", path)

    log.info("Update complete: %s matches", total)

if __name__ == "__main__":
    main()
