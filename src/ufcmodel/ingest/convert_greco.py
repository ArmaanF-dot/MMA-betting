"""Convert the Greco1899/scrape_ufc_stats CSVs (UFCStats data: per-round stats by target and position, control time,
referee, method, current to the file's date) into the per-table CSVs `load_csv` expects.

Odds are not in this dataset: they are matched on from the older jansen88 odds file (betmma.tips, 2014 to 2023-09) by
fighter-name pair and date. Fighters whose name appears more than once in the source cannot be told apart from names alone
and are merged into one id with blank physicals (logged).
"""
import csv
import difflib
import hashlib
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

from ufcmodel.db import STAT_COLS
from ufcmodel.ingest.convert_ufc_data import _parse_odds_date, slug

DIVISIONS = ["Women's Strawweight", "Women's Flyweight", "Women's Bantamweight", "Women's Featherweight", "Super Heavyweight",
             "Light Heavyweight", "Heavyweight", "Middleweight", "Welterweight", "Lightweight", "Featherweight", "Bantamweight",
             "Flyweight", "Strawweight", "Open Weight", "Catch Weight"]
FUZZY_MIN = 0.88
WINDOW = 2


def _read(con, path):
    cur = con.execute(f"SELECT * FROM read_csv('{Path(path).as_posix()}', header=true, all_varchar=true, sample_size=-1)")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _of(s):
    m = re.fullmatch(r"\s*(\d+) of (\d+)\s*", s or "")
    return (int(m[1]), int(m[2])) if m else (None, None)


def _int(s):
    """UFCStats counts arrive as '0', '1' or '1.0'; blanks and dashes are missing."""
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def _ctrl(s):
    m = re.fullmatch(r"\s*(\d+):(\d+)\s*", s or "")
    return int(m[1]) * 60 + int(m[2]) if m else None


def _id(url, fallback):
    return url.rstrip("/").split("/")[-1] if url else hashlib.md5(fallback.encode()).hexdigest()[:16]


def _division(wc):
    for d in DIVISIONS:
        if d.lower() in wc.lower():
            return d
    return re.sub(r"\b(UFC|Title|Bout|Interim)\b", "", wc).strip() or wc


def _lengths(fmt):
    m = re.search(r"\(([\d\-]+)\)", fmt or "")
    return [int(x) for x in m[1].split("-")] if m else None


def _method(m, details):
    m = (m or "").strip()
    if m.startswith("Decision"):
        return "Decision", m.split("-")[-1].strip()
    if m == "KO/TKO":
        return "KO/TKO", (details or "").strip()
    if m.startswith("TKO"):
        return "KO/TKO", "Doctor's stoppage"
    if m == "Submission":
        return "Submission", (details or "").strip()
    return {"Could Not Continue": "Could Not Continue", "DQ": "DQ", "Overturned": "No Contest", "Other": "Other"}.get(m, m), ""


def _write(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def convert(src_dir, out_dir, odds_file=None, interim_dir=None) -> dict:
    src, out = Path(src_dir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    stats: dict = {}

    # fighters ---------------------------------------------------------------------------
    tott = _read(con, src / "ufc_fighter_tott.csv")
    by_name = defaultdict(list)
    for r in tott:
        by_name[r["FIGHTER"].strip()].append(r)
    fighters, name_to_id, ambiguous = {}, {}, []
    for name, rows in by_name.items():
        if len(rows) > 1:
            ambiguous.append(name)
            fid = "x-" + slug(name)
            fighters[fid] = dict(fighter_id=fid, name=name, dob="", height_cm="", reach_cm="", stance="")
            name_to_id[name] = fid
            continue
        r = rows[0]
        fid = _id(r["URL"], name)
        h = re.fullmatch(r"(\d+)'\s*(\d+)\"?", r["HEIGHT"].strip())
        rc = re.fullmatch(r"(\d+(?:\.\d+)?)\"?", r["REACH"].strip())
        try:
            dob = datetime.strptime(r["DOB"].strip(), "%b %d, %Y").date().isoformat()
        except ValueError:
            dob = ""
        fighters[fid] = dict(fighter_id=fid, name=name, dob=dob, stance=r["STANCE"] or "",
                             height_cm=round((int(h[1]) * 12 + int(h[2])) * 2.54, 1) if h else "",
                             reach_cm=round(float(rc[1]) * 2.54, 1) if rc else "")
        name_to_id[name] = fid
    stats["ambiguous_fighter_names"] = sorted(ambiguous)

    def fid_of(name):
        name = name.strip()
        if name not in name_to_id:
            fid = "x-" + slug(name)
            fighters.setdefault(fid, dict(fighter_id=fid, name=name, dob="", height_cm="", reach_cm="", stance=""))
            name_to_id[name] = fid
            stats["fighters_not_in_tott"] = stats.get("fighters_not_in_tott", 0) + 1
        return name_to_id[name]

    # events and bouts -------------------------------------------------------------------
    events = {}
    for r in _read(con, src / "ufc_event_details.csv"):
        d = datetime.strptime(r["DATE"].strip(), "%B %d, %Y").date().isoformat()
        parts = [p.strip() for p in r["LOCATION"].split(",")]
        events[r["EVENT"].strip()] = dict(event_id=_id(r["URL"], r["EVENT"]), name=r["EVENT"].strip(), date=d,
                                          city=parts[0], country=parts[-1], venue="")
    bouts, bout_fighter, aliases, key_to_bout, seen = [], [], [], {}, set()
    pos = defaultdict(int)
    skipped_names = dup = no_event = 0
    for r in _read(con, src / "ufc_fight_results.csv"):
        ev = events.get(r["EVENT"].strip())
        if ev is None:
            no_event += 1
            continue
        names = r["BOUT"].split(" vs. ")
        if len(names) != 2:
            skipped_names += 1
            continue
        bid = _id(r["URL"], ev["event_id"] + r["BOUT"])
        if bid in seen:
            dup += 1
            continue
        seen.add(bid)
        a, b = (fid_of(n) for n in names)
        key_to_bout[(r["EVENT"].strip(), r["BOUT"])] = (bid, a, b)
        pos[ev["event_id"]] += 1
        lengths = _lengths(r["TIME FORMAT"])
        end_round = _int(r["ROUND"])
        mm, _, ss = (r["TIME"] or "").partition(":")
        end_time = int(mm) * 60 + int(ss) if mm.isdigit() and ss.isdigit() else None
        fight_sec = ""
        if end_round and end_time is not None:
            prior = sum(lengths[:end_round - 1]) * 60 if lengths and len(lengths) >= end_round - 1 else (end_round - 1) * 300
            fight_sec = prior + end_time
        method, detail = _method(r["METHOD"], r["DETAILS"])
        bouts.append(dict(
            bout_id=bid, event_id=ev["event_id"], weight_class=_division(r["WEIGHTCLASS"]),
            is_title="true" if "Title" in r["WEIGHTCLASS"] else "false", scheduled_rounds=len(lengths) if lengths else "",
            method=method, method_detail=detail, end_round=end_round or "", end_time_sec=end_time if end_time is not None else "",
            referee=(r["REFEREE"] or "").strip(), card_position=pos[ev["event_id"]],
            round_lengths=",".join(map(str, lengths)) if lengths else "", fight_seconds=fight_sec))
        res = {"W/L": ("win", "loss"), "L/W": ("loss", "win"), "D/D": ("draw", "draw"), "NC/NC": ("nc", "nc")}[r["OUTCOME"].strip()]
        red_first = hashlib.md5(bid.encode()).digest()[0] % 2 == 0   # corner by hash: list order is not a corner
        c1, c2 = ("red", "blue") if red_first else ("blue", "red")
        bout_fighter += [dict(bout_id=bid, fighter_id=a, corner=c1, result=res[0]),
                         dict(bout_id=bid, fighter_id=b, corner=c2, result=res[1])]
        aliases += [dict(alias=names[0].strip(), fighter_id=a, source="ufcstats"), dict(alias=names[1].strip(), fighter_id=b, source="ufcstats")]
    stats.update(events=len({b["event_id"] for b in bouts}), bouts=len(bouts), duplicate_bout_ids_dropped=dup,
                 unparsable_bout_names=skipped_names, results_without_event=no_event)

    # rounds -----------------------------------------------------------------------------
    rounds, orphan = [], 0
    for r in _read(con, src / "ufc_fight_stats.csv"):
        key = (r["EVENT"].strip(), r["BOUT"])
        rn = re.fullmatch(r"Round (\d+)", r["ROUND"] or "")
        if key not in key_to_bout or not rn:
            orphan += 1
            continue
        bid, a, b = key_to_bout[key]
        fid = fid_of(r["FIGHTER"])
        if fid not in (a, b):
            orphan += 1
            continue
        row = dict(bout_id=bid, fighter_id=fid, round=int(rn[1]), kd=_int(r["KD"]), sub_att=_int(r["SUB.ATT"]),
                   rev=_int(r["REV."]), ctrl_sec=_ctrl(r["CTRL"]))
        for col, src_col in (("sig", "SIG.STR."), ("total", "TOTAL STR."), ("td", "TD"), ("head", "HEAD"), ("body", "BODY"),
                             ("leg", "LEG"), ("dist", "DISTANCE"), ("clinch", "CLINCH"), ("ground", "GROUND")):
            row[f"{col}_l"], row[f"{col}_a"] = _of(r[src_col])
        rounds.append(row)
    stats.update(round_rows=len(rounds), stat_rows_unmatched=orphan)
    totals = defaultdict(lambda: {c: 0 for c in STAT_COLS})
    bad = defaultdict(set)
    for r in rounds:
        for c in STAT_COLS:
            if r[c] is None:
                bad[(r["bout_id"], r["fighter_id"])].add(c)
            else:
                totals[(r["bout_id"], r["fighter_id"])][c] += r[c]
    bout_totals = [dict(bout_id=k[0], fighter_id=k[1], **{c: (None if c in bad[k] else v[c]) for c in STAT_COLS})
                   for k, v in totals.items()]

    # odds -------------------------------------------------------------------------------
    odds, unmatched, used, exact, fuzzy, bad_price = [], [], set(), 0, 0, 0
    if odds_file and Path(odds_file).exists():
        ev_date = {b["bout_id"]: next(e["date"] for e in events.values() if e["event_id"] == b["event_id"]) for b in bouts}
        fs = defaultdict(list)
        for bf in bout_fighter:
            fs[bf["bout_id"]].append(bf["fighter_id"])
        by_pair, by_date = defaultdict(list), defaultdict(list)
        for bid, (x, y) in fs.items():
            by_pair[frozenset((x, y))].append(bid)
            by_date[date.fromisoformat(ev_date[bid])].append(bid)
        names_of = {f["fighter_id"]: slug(f["name"]) for f in fighters.values()}
        sl_to_id = defaultdict(list)
        for fid, n in names_of.items():
            sl_to_id[n].append(fid)
        for r in _read(con, odds_file):
            d = _parse_odds_date(r["date"])
            o1, o2 = float(r["fighter1_odds"]), float(r["fighter2_odds"])
            if not (1 < o1 < 1000 and 1 < o2 < 1000):
                bad_price += 1
                continue
            s1, s2 = slug(r["fighter1"]), slug(r["fighter2"])
            ids1, ids2 = sl_to_id.get(s1, []), sl_to_id.get(s2, [])
            cands = [b for i1 in ids1 for i2 in ids2 for b in by_pair.get(frozenset((i1, i2)), [])
                     if abs((date.fromisoformat(ev_date[b]) - d).days) <= WINDOW]
            how = "exact"
            if not cands:
                best, score = None, 0.0
                for k in range(-WINDOW, WINDOW + 1):
                    for b in by_date.get(d + timedelta(days=k), []):
                        x, y = fs[b]
                        sc = max(min(difflib.SequenceMatcher(None, s1, names_of[x]).ratio(), difflib.SequenceMatcher(None, s2, names_of[y]).ratio()),
                                 min(difflib.SequenceMatcher(None, s1, names_of[y]).ratio(), difflib.SequenceMatcher(None, s2, names_of[x]).ratio()))
                        if sc > score:
                            best, score = b, sc
                if best and score >= FUZZY_MIN:
                    cands, how = [best], "fuzzy"
            if not cands:
                unmatched.append(dict(date=d.isoformat(), event=r["event"], fighter1=r["fighter1"], fighter2=r["fighter2"]))
                continue
            bid = cands[0]
            if bid in used:
                continue
            used.add(bid)
            exact += how == "exact"
            fuzzy += how == "fuzzy"
            x, y = fs[bid]
            direct = (difflib.SequenceMatcher(None, s1, names_of[x]).ratio() + difflib.SequenceMatcher(None, s2, names_of[y]).ratio()
                      >= difflib.SequenceMatcher(None, s1, names_of[y]).ratio() + difflib.SequenceMatcher(None, s2, names_of[x]).ratio())
            a1, a2 = (x, y) if direct else (y, x)
            for fid, o in ((a1, o1), (a2, o2)):
                odds.append(dict(bout_id=bid, bookmaker="betmma.tips", ts="", fighter_id=fid, price_decimal=o, kind="unknown"))
            if how == "fuzzy":
                aliases += [dict(alias=r["fighter1"], fighter_id=a1, source="betmma_fuzzy"), dict(alias=r["fighter2"], fighter_id=a2, source="betmma_fuzzy")]
    stats.update(odds_matched_exact=exact, odds_matched_fuzzy=fuzzy, odds_unmatched=len(unmatched), odds_bad_price=bad_price)

    # write ------------------------------------------------------------------------------
    used_f = {bf["fighter_id"] for bf in bout_fighter}
    seen_al, uniq = set(), []
    for a in aliases:
        k = (a["alias"], a["fighter_id"])
        if k not in seen_al:
            seen_al.add(k)
            uniq.append(a)
    _write(out / "events.csv", [e for e in events.values() if e["event_id"] in {b["event_id"] for b in bouts}],
           ["event_id", "name", "date", "city", "country", "venue"])
    _write(out / "fighters.csv", [f for f in fighters.values() if f["fighter_id"] in used_f],
           ["fighter_id", "name", "dob", "height_cm", "reach_cm", "stance"])
    _write(out / "fighter_aliases.csv", uniq, ["alias", "fighter_id", "source"])
    _write(out / "bouts.csv", bouts, ["bout_id", "event_id", "weight_class", "is_title", "scheduled_rounds", "method", "method_detail",
                                      "end_round", "end_time_sec", "referee", "card_position", "round_lengths", "fight_seconds"])
    _write(out / "bout_fighter.csv", bout_fighter, ["bout_id", "fighter_id", "corner", "result"])
    _write(out / "rounds.csv", rounds, ["bout_id", "fighter_id", "round"] + STAT_COLS)
    _write(out / "bout_totals.csv", bout_totals, ["bout_id", "fighter_id"] + STAT_COLS)
    _write(out / "odds_snapshots.csv", odds, ["bout_id", "bookmaker", "ts", "fighter_id", "price_decimal", "kind"])
    if interim_dir:
        Path(interim_dir).mkdir(parents=True, exist_ok=True)
        _write(Path(interim_dir) / "odds_unmatched.csv", unmatched, ["date", "event", "fighter1", "fighter2"])
    return stats
