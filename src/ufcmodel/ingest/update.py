"""`ufcmodel update`: refresh the six Greco1899/scrape_ufc_stats CSVs from GitHub, then convert, load and run the QA checks.

Six requests, cached copies kept until the new files validate. The source repository refreshes its CSVs itself from UFCStats on
a schedule, so this does not hit ufcstats.com. The files are GPL-3.0 code's output of UFCStats data: keep them local and never
redistribute them (spec principle 7). A failed validation or a failed QA leaves the previous data in place.
"""
import shutil
import sys
import time
from pathlib import Path

import httpx

from ufcmodel.config import ROOT, load_config
from ufcmodel.db import connect
from ufcmodel.ingest.convert_greco import convert
from ufcmodel.ingest.load_csv import load_csv_dir
from ufcmodel.qa.checks import report, run_checks

BASE = "https://raw.githubusercontent.com/Greco1899/scrape_ufc_stats/main/"
FILES = {"ufc_event_details.csv": "EVENT,URL,DATE,LOCATION",
         "ufc_fight_details.csv": "EVENT,BOUT,URL",
         "ufc_fight_results.csv": "EVENT,BOUT,OUTCOME,WEIGHTCLASS,METHOD,ROUND,TIME,TIME FORMAT,REFEREE,DETAILS,URL",
         "ufc_fight_stats.csv": "EVENT,BOUT,ROUND,FIGHTER,KD,SIG.STR.,SIG.STR. %,TOTAL STR.,TD,TD %,SUB.ATT,REV.,CTRL,HEAD,BODY,LEG,DISTANCE,CLINCH,GROUND",
         "ufc_fighter_details.csv": None, "ufc_fighter_tott.csv": "FIGHTER,HEIGHT,WEIGHT,REACH,STANCE,DOB,URL"}
MIN_ROWS = {"ufc_fight_results.csv": 8000, "ufc_fight_stats.csv": 40000}


def update(raw_dir=None, ua="ufc-model-research/0.1", delay=2.0) -> int:
    raw = Path(raw_dir or ROOT / "data" / "raw" / "greco")
    stage = raw.parent / "greco_incoming"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    with httpx.Client(headers={"User-Agent": ua}, timeout=60, follow_redirects=True) as c:
        for name, header in FILES.items():
            r = c.get(BASE + name)
            r.raise_for_status()
            text = r.text
            if header and not text.startswith(header):
                print(f"{name}: unexpected header, keeping the previous files", file=sys.stderr)
                return 2
            if len(text.splitlines()) < MIN_ROWS.get(name, 100):
                print(f"{name}: too few rows ({len(text.splitlines())}), keeping the previous files", file=sys.stderr)
                return 2
            (stage / name).write_text(text, encoding="utf-8")
            time.sleep(delay)
    cfg = load_config()
    con = connect(ROOT / cfg["database"])
    before = con.execute("SELECT count(*) FROM bouts").fetchone()[0]
    backup = raw.parent / "greco_previous"
    shutil.rmtree(backup, ignore_errors=True)
    if raw.exists():
        shutil.copytree(raw, backup)
    shutil.copytree(stage, raw, dirs_exist_ok=True)
    stats = convert(raw, ROOT / "data" / "raw" / "csv", raw.parent / "ufc_dataset" / "odds_raw.csv", ROOT / "data" / "interim")
    load_csv_dir(con, ROOT / "data" / "raw" / "csv")
    text, hard = report(run_checks(con, cfg["qa"]["round_seconds"], (cfg["qa"]["overround_min"], cfg["qa"]["overround_max"])))
    print(text)
    after = con.execute("SELECT count(*) FROM bouts").fetchone()[0]
    print(f"bouts: {before} -> {after} ({after - before:+d}); latest event: " + str(con.execute("SELECT max(date) FROM events").fetchone()[0]))
    if hard:
        print("QA failed: restoring the previous raw files (rerun `make data` after fixing)", file=sys.stderr)
        shutil.rmtree(raw)
        shutil.copytree(backup, raw)
        return 1
    shutil.rmtree(stage, ignore_errors=True)
    return 0
