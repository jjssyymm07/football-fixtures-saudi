import os
import re
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
API_URL = "https://v3.football.api-sports.io"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("football-calendar")

API_KEY = os.environ.get("APISPORTS_KEY")

def load_config():
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)

def api_request(endpoint, params):
    if not API_KEY:
        raise RuntimeError("Missing APISPORTS_KEY secret")

    response = requests.get(
        f"{API_URL}/{endpoint}",
        headers={"x-apisports-key": API_KEY},
        params=params,
        timeout=45
    )
    response.raise_for_status()
    data = response.json()

    if data.get("errors"):
        raise RuntimeError(str(data["errors"]))

    return data.get("response", [])

def safe_name(value):
    return re.sub(r"[^a-z0-9_-]", "-", value.lower()).strip("-")

def new_calendar(name):
    cal = Calendar()
    cal.add("prodid", "-//Football Fixtures Saudi//AR")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", name)
    cal.add("x-wr-timezone", "Asia/Riyadh")
    return cal

def add_match(cal, fixture):
    info = fixture["fixture"]
    teams = fixture["teams"]
    league = fixture["league"]
    goals = fixture.get("goals") or {}

    kickoff = datetime.fromisoformat(
        info["date"].replace("Z", "+00:00")
    ).astimezone(RIYADH)

    home = teams["home"]["name"]
    away = teams["away"]["name"]
    status = info["status"]["long"]
    short_status = info["status"]["short"]

    score = ""
    if goals.get("home") is not None and goals.get("away") is not None:
        score = f" | {goals['home']} - {goals['away']}"

    event = Event()
    event.add("uid", f"fixture-{info['id']}@football-fixtures-saudi")
    event.add("summary", f"{home} vs {away}{score}")
    event.add("dtstart", kickoff)
    event.add("dtend", kickoff + timedelta(hours=2))
    event.add("dtstamp", datetime.now(timezone.utc))
    event.add("location", info.get("venue", {}).get("name") or "")

    description = [
        f"Competition: {league['name']}",
        f"Home: {home}",
        f"Away: {away}",
        f"Saudi time: {kickoff.strftime('%Y-%m-%d %H:%M')}",
        f"Status: {status}",
        f"Score: {score or 'Not available'}",
        f"Venue: {info.get('venue', {}).get('name') or 'Not announced'}",
        "Broadcast: Not available from this API source"
    ]
    event.add("description", "\n".join(description))
    event.add("categories", [league["name"]])

    if short_status == "CANC":
        event.add("status", "CANCELLED")
    else:
        event.add("status", "CONFIRMED")

    alarm = Alarm()
    alarm.add("action", "DISPLAY")
    alarm.add("description", f"Match starting: {home} vs {away}")
    alarm.add("trigger", timedelta(minutes=-30))
    event.add_component(alarm)

    cal.add_component(event)

def main():
    config = load_config()
    season = int(config.get("season", datetime.now().year))
    leagues = config.get("leagues", [])

    OUTPUT_DIR.mkdir(exist_ok=True)

    calendars = {"all": new_calendar("Football Fixtures - All")}
    counts = {}

    for league in leagues:
        name = league["name"]
        group = safe_name(league.get("group", "other"))
        league_id = int(league["code"])

        if group not in calendars:
            calendars[group] = new_calendar(
                f"Football Fixtures - {group}"
            )

        try:
            matches = api_request(
                "fixtures",
                {"league": league_id, "season": season}
            )

            added = 0
            for match in matches:
                add_match(calendars["all"], match)
                add_match(calendars[group], match)
                added += 1

            counts[name] = added
            log.info("%s: %s fixtures", name, added)

        except Exception as exc:
            log.exception("Failed to update %s: %s", name, exc)

    for name, cal in calendars.items():
        path = OUTPUT_DIR / f"{name}.ics"
        path.write_bytes(cal.to_ical())
        log.info("Created %s", path)

    log.info("Update complete: %s", counts)

if __name__ == "__main__":
    main()
