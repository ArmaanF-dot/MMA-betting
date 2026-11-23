"""Scheduled odds capture for the forward test. A Windows scheduled task runs `python -m ufcmodel.reports.capture` every 15 minutes;
each tick is cheap and local, and only does network work when something is due:
  discovery  at most every 6 hours: read the odds site's front page for UFC events in the next 14 days (one page)
  slots      per event, in the machine's local time (assumed to be the bettor's):
               listed  the first time the event is seen
               mon     Monday of fight week, 12:00
               thu     Thursday of fight week, 12:00
               pre     the evening before the fights, as the closing proxy: 20:00 the night before when the site's event date is a
                       Sunday (a US Saturday card is on a Sunday by UK date), else 15:00 on the event date.
                       Start times are not on the site, so this is an ASSUMPTION; change PRE_* below if it proves wrong.
Each due slot runs `ufcmodel.reports.livecard ... --slot <slot>`, which logs the prices and predictions with that label. A slot is
retried every tick for a few hours when it fails (for example the database is busy) and is recorded as missed after its window.
State is kept in data/paper/capture_state.json and a log in data/paper/capture.log."""
import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from ufcmodel.ingest.bfo import BASE, HEADERS

ROOT = Path(__file__).resolve().parents[3]
STATE, LOG = Path("data/paper/capture_state.json"), Path("data/paper/capture.log")
DISCOVER_EVERY = timedelta(hours=6)
WINDOW = {"mon": timedelta(hours=8), "thu": timedelta(hours=8), "pre": timedelta(hours=3)}
MAX_ATTEMPTS = 6
PRE_SUNDAY_EVE = (20, 0)    # local time on the day before, for a Sunday event date
PRE_OTHER = (15, 0)         # local time on the event date otherwise
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1)}


def slot_times(event_date: date) -> dict[str, datetime]:
    """Local capture times for the fight week of an event with this site date."""
    eve = event_date.weekday() == 6
    fight_day = event_date - timedelta(days=1) if eve else event_date
    at = lambda d, hm: datetime(d.year, d.month, d.day, hm[0], hm[1])
    return {"mon": at(fight_day - timedelta(days=fight_day.weekday()), (12, 0)),
            "thu": at(fight_day - timedelta(days=(fight_day.weekday() - 3) % 7), (12, 0)),
            "pre": at(fight_day, PRE_SUNDAY_EVE) if eve else at(event_date, PRE_OTHER)}


def due_slots(now: datetime, event_date: date, done: dict) -> tuple[list[str], list[str]]:
    """(slots to run now, slots whose window has passed unrecorded). `done` maps slot -> a status string, anything already settled."""
    run, missed = [], []
    for slot, t in slot_times(event_date).items():
        if slot in done:
            continue
        if t <= now < t + WINDOW[slot]:
            run.append(slot)
        elif now >= t + WINDOW[slot]:
            missed.append(slot)
    return run, missed


def parse_upcoming(html: str, today: date) -> list[dict]:
    """UFC events listed on the front page: [{slug, url, date}], from links reading 'View <name> Odds (<Month> <day>th) ->'."""
    out, seen = [], set()
    for a in BeautifulSoup(html, "lxml").find_all("a", href=re.compile(r"^/events/ufc")):
        m = re.search(r"\((\w+) (\d{1,2})(?:st|nd|rd|th)\)", a.get_text(" ", strip=True))
        if not m or m.group(1) not in MONTHS or a["href"] in seen:
            continue
        d = date(today.year, MONTHS[m.group(1)], int(m.group(2)))
        if d < today - timedelta(days=60):
            d = date(today.year + 1, d.month, d.day)
        seen.add(a["href"])
        out.append(dict(slug=a["href"].rsplit("/", 1)[-1], url=BASE + a["href"], date=d.isoformat()))
    return out


def log(msg: str):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"last_discovery": None, "events": {}}


def save_state(st: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1), encoding="utf-8")


def discover(st: dict, now: datetime):
    r = httpx.get(BASE + "/", headers=HEADERS, timeout=60, follow_redirects=True)
    low = r.text.lower()
    if r.status_code != 200 or any(m in low for m in ("captcha", "just a moment", "cf-chl", "access denied")):
        log(f"discovery stopped: status {r.status_code} or a bot check; not working around it")
        return
    found = parse_upcoming(r.text, now.date())
    for e in found:
        d = date.fromisoformat(e["date"])
        if not now.date() - timedelta(days=1) <= d <= now.date() + timedelta(days=14):
            continue
        if e["slug"] not in st["events"]:
            st["events"][e["slug"]] = dict(url=e["url"], date=e["date"], slots={"listed": "pending"})
            log(f"new event listed: {e['slug']} on {e['date']}")
    st["last_discovery"] = now.isoformat(timespec="seconds")


def run_capture(url: str, event_date: str, slot: str) -> tuple[bool, str]:
    p = subprocess.run([sys.executable, "-m", "ufcmodel.reports.livecard", url, event_date, "--slot", slot], capture_output=True, text=True,
                       timeout=1500, cwd=ROOT)
    tail = (p.stdout.strip().splitlines() or [""])[0] if p.returncode == 0 else (p.stderr.strip().splitlines() or ["no error text"])[-1]
    return p.returncode == 0, tail


def tick(now: datetime, dry_run=False, skip_discovery=False):
    st = load_state()
    last = datetime.fromisoformat(st["last_discovery"]) if st["last_discovery"] else None
    if not skip_discovery and (last is None or now - last >= DISCOVER_EVERY):
        try:
            discover(st, now)
        except Exception as e:                     # a failed read of the front page must never stop the slots
            log(f"discovery failed: {type(e).__name__}: {e}")
    for slug, ev in sorted(st["events"].items()):
        d = date.fromisoformat(ev["date"])
        if now.date() > d + timedelta(days=1):
            continue
        slots = ev["slots"]
        settled = {k: v for k, v in slots.items() if v != "pending" and not v.startswith("retry")}
        todo = (["listed"] if slots.get("listed") == "pending" or str(slots.get("listed", "")).startswith("retry") else [])
        run, missed = due_slots(now, d, settled)
        for m in missed:
            if m not in slots:
                slots[m] = "missed"
                log(f"{slug}: slot {m} was before this event was seen or its window has passed: missed")
        todo += [s for s in run if not str(slots.get(s, "")).startswith("gave up")]
        for slot in todo:
            tries = int(str(slots.get(slot, "retry 0")).split()[-1]) if str(slots.get(slot, "")).startswith("retry") else 0
            if dry_run:
                log(f"DRY RUN {slug}: would capture slot {slot}")
                continue
            ok, msg = run_capture(ev["url"], ev["date"], slot)
            if ok:
                slots[slot] = f"done {now.isoformat(timespec='minutes')}"
                log(f"{slug}: slot {slot} captured. {msg}")
            else:
                slots[slot] = f"retry {tries + 1}" if tries + 1 < MAX_ATTEMPTS else "gave up"
                log(f"{slug}: slot {slot} failed ({slots[slot]}): {msg}")
            save_state(st)
    if not dry_run:
        save_state(st)


if __name__ == "__main__":
    import os
    os.chdir(ROOT)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="say what would be captured, run nothing")
    ap.add_argument("--now", help="pretend it is this local time, YYYY-MM-DD HH:MM (testing)")
    ap.add_argument("--no-discovery", action="store_true")
    a = ap.parse_args()
    tick(datetime.strptime(a.now, "%Y-%m-%d %H:%M") if a.now else datetime.now(), a.dry_run, a.no_discovery)
