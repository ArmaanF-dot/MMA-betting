"""Convert the jansen88/ufc-data raw CSVs into the per-table CSVs that `load_csv` expects.

Source files: events_raw.csv (one row per bout, listed winner first), fighters_raw.csv,
odds_raw.csv (betmma.tips, one decimal-odds pair per bout).

What it deliberately does NOT carry over: the fighters' career averages (SLpM, Str.Acc., ...).
They were scraped once in Sept 2023, so they include each fighter's later fights and would leak.
"""
import csv
import difflib
import hashlib
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

FUZZY_MIN = 0.88  # both names must reach this ratio to auto-accept an odds match
DATE_WINDOW_DAYS = 2


def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _read(con, path: Path) -> list[dict]:
    cur = con.execute(f"SELECT * FROM read_csv('{path.as_posix()}', header=true, all_varchar=true)")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _nums(s: str) -> list[int | None]:
    """'3   1' -> [3, 1]; '--' (older bouts without stats) -> [None, None]."""
    parts = (s or "").split()
    return [int(x) for x in parts] if len(parts) == 2 and all(x.isdigit() for x in parts) else [None, None]


def _parse_height_cm(s):
    m = re.fullmatch(r"(\d+)'\s*(\d+)\"?", (s or "").strip())
    return round((int(m[1]) * 12 + int(m[2])) * 2.54, 1) if m else None


def _parse_reach_cm(s):
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\"?", (s or "").strip())
    return round(float(m[1]) * 2.54, 1) if m else None


def _parse_dob(s):
    try:
        return datetime.strptime((s or "").strip(), "%b%d,%Y").date().isoformat()
    except ValueError:
        return None


def _parse_odds_date(s: str) -> date:
    return datetime.strptime(re.sub(r"(\d)(st|nd|rd|th)", r"\1", s.strip()), "%d %b %y").date()


def _is_red(bout_id: str) -> bool:
    """Source lists the winner as fighter1, so corner must not follow list order."""
    return hashlib.md5(bout_id.encode()).digest()[0] % 2 == 0


def _write(path: Path, rows: list[dict], cols: list[str]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def convert(src_dir, out_dir, interim_dir=None) -> dict:
    src, out = Path(src_dir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    interim = Path(interim_dir) if interim_dir else None
    if interim:
        interim.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    ev_rows = _read(con, src / "events_raw.csv")
    fi_rows = _read(con, src / "fighters_raw.csv")
    od_rows = _read(con, src / "odds_raw.csv")
    stats: dict = {}

    # fighters ---------------------------------------------------------------------------
    by_name: dict[str, list[dict]] = defaultdict(list)
    for r in fi_rows:
        by_name[r["name"]].append(r)
    fighters: dict[str, dict] = {}
    ambiguous = []
    for name, rows in by_name.items():
        fid = slug(name)
        if len(rows) > 1:  # events carry names only, so duplicates cannot be told apart
            ambiguous.append(name)
            fighters[fid] = dict(fighter_id=fid, name=name, dob="", height_cm="", reach_cm="", stance="")
            continue
        r = rows[0]
        fighters[fid] = dict(
            fighter_id=fid, name=name, dob=_parse_dob(r["DOB"]) or "",
            height_cm=_parse_height_cm(r["Height"]) or "", reach_cm=_parse_reach_cm(r["Reach"]) or "",
            stance=r["STANCE"] or "",
        )
    stats["ambiguous_fighter_names"] = sorted(ambiguous)

    # events / bouts ---------------------------------------------------------------------
    events: dict[str, dict] = {}
    bouts, bout_fighter, totals, aliases = [], [], [], []
    seen_pairs, idx_in_event = set(), defaultdict(int)
    dup_bouts = unknown_method = 0
    for r in ev_rows:
        d = datetime.strptime(r["event_date"].strip(), "%B %d %Y").date()
        eid = f"{slug(r['event_name'])}-{d.isoformat()}"
        if eid not in events:
            parts = [p.strip() for p in r["event_location"].split(",")]
            events[eid] = dict(event_id=eid, name=r["event_name"], date=d.isoformat(),
                               city=parts[0], country=parts[-1], venue="")
        f1, f2 = slug(r["fighter1"]), slug(r["fighter2"])
        if (eid, frozenset((f1, f2))) in seen_pairs:
            dup_bouts += 1
            continue
        seen_pairs.add((eid, frozenset((f1, f2))))
        for f, n in ((f1, r["fighter1"]), (f2, r["fighter2"])):
            if f not in fighters:
                fighters[f] = dict(fighter_id=f, name=n, dob="", height_cm="", reach_cm="", stance="")
        idx_in_event[eid] += 1
        bid = f"{eid}-{idx_in_event[eid]:02d}"
        toks = r["Method"].split()
        code = toks[0] if toks else ""
        method = {"U-DEC": "Decision", "S-DEC": "Decision", "M-DEC": "Decision", "SUB": "Submission",
                  "CNC": "No Contest"}.get(code, code)
        detail = " ".join(toks[1:]) if code in ("KO/TKO", "SUB") else code if method == "Decision" else ""
        if code in ("", "-"):
            unknown_method += 1
        mm, _, ss = (r["Time"] or "").partition(":")
        bouts.append(dict(
            bout_id=bid, event_id=eid, weight_class=r["Weight class"], is_title="", scheduled_rounds="",
            method=method, method_detail=detail, end_round=r["Round"],
            end_time_sec=int(mm) * 60 + int(ss) if mm.isdigit() and ss.isdigit() else "",
            referee="", card_position=idx_in_event[eid],
        ))
        res1, res2 = {"fighter1": ("win", "loss"), "Draw": ("draw", "draw"),
                      "No contest": ("nc", "nc")}[r["outcome"]]
        c1, c2 = ("red", "blue") if _is_red(bid) else ("blue", "red")
        bout_fighter += [dict(bout_id=bid, fighter_id=f1, corner=c1, result=res1),
                         dict(bout_id=bid, fighter_id=f2, corner=c2, result=res2)]
        kd, sig, td, sub = (_nums(r[k]) for k in ("Kd", "Str", "Td", "Sub"))
        for i, f in enumerate((f1, f2)):
            totals.append(dict(bout_id=bid, fighter_id=f, kd=kd[i], sig_l=sig[i], td_l=td[i], sub_att=sub[i]))
        aliases += [dict(alias=r["fighter1"], fighter_id=f1, source="ufcstats"),
                    dict(alias=r["fighter2"], fighter_id=f2, source="ufcstats")]
    stats.update(events=len(events), bouts=len(bouts), duplicate_bouts_dropped=dup_bouts,
                 bouts_without_method=unknown_method, fighters=len(fighters))

    # odds -------------------------------------------------------------------------------
    pair_index = defaultdict(list)  # frozenset of fighter ids -> [(date, bout_id, winner_id)]
    bout_ev_date = {b["bout_id"]: events[b["event_id"]]["date"] for b in bouts}
    fids_by_bout = defaultdict(list)
    for bf in bout_fighter:
        fids_by_bout[bf["bout_id"]].append(bf)
    by_date = defaultdict(list)
    for bid, fs in fids_by_bout.items():
        pair_index[frozenset(f["fighter_id"] for f in fs)].append(bid)
        by_date[date.fromisoformat(bout_ev_date[bid])].append(bid)
    names = {f["fighter_id"]: f["name"] for f in fighters.values()}

    def near(d: date):
        return [b for k in range(-DATE_WINDOW_DAYS, DATE_WINDOW_DAYS + 1)
                for b in by_date.get(d + timedelta(days=k), [])]

    odds, unmatched, used = [], [], set()
    exact = fuzzy = dup_odds = bad_price = winner_mismatch = 0
    for r in od_rows:
        d = _parse_odds_date(r["date"])
        o1, o2 = float(r["fighter1_odds"]), float(r["fighter2_odds"])
        if not (1 < o1 < 1000 and 1 < o2 < 1000):  # source writes missing odds as inf
            bad_price += 1
            continue
        key = frozenset((slug(r["fighter1"]), slug(r["fighter2"])))
        cands = [b for b in pair_index.get(key, []) if abs((date.fromisoformat(bout_ev_date[b]) - d).days) <= DATE_WINDOW_DAYS]
        how = "exact"
        if not cands:
            best, best_score = None, 0.0
            for b in near(d):
                a, c = (f["fighter_id"] for f in fids_by_bout[b])
                direct = min(difflib.SequenceMatcher(None, slug(r["fighter1"]), a).ratio(),
                             difflib.SequenceMatcher(None, slug(r["fighter2"]), c).ratio())
                swap = min(difflib.SequenceMatcher(None, slug(r["fighter1"]), c).ratio(),
                           difflib.SequenceMatcher(None, slug(r["fighter2"]), a).ratio())
                sc = max(direct, swap)
                if sc > best_score:
                    best, best_score = b, sc
            if best and best_score >= FUZZY_MIN:
                cands, how = [best], "fuzzy"
        if not cands:
            unmatched.append(dict(date=d.isoformat(), event=r["event"], fighter1=r["fighter1"],
                                  fighter2=r["fighter2"]))
            continue
        bid = cands[0]
        if bid in used:
            dup_odds += 1
            continue
        used.add(bid)
        exact += how == "exact"
        fuzzy += how == "fuzzy"
        fs = {f["fighter_id"]: f for f in fids_by_bout[bid]}
        # map odds-side names to fighter ids (by closeness; exact slug first)
        def side(name):
            s = slug(name)
            if s in fs:
                return s
            return max(fs, key=lambda f: difflib.SequenceMatcher(None, s, f).ratio())
        a1 = side(r["fighter1"])
        a2 = next(f for f in fs if f != a1)
        if how == "fuzzy":
            aliases += [dict(alias=r["fighter1"], fighter_id=a1, source="betmma_fuzzy"),
                        dict(alias=r["fighter2"], fighter_id=a2, source="betmma_fuzzy")]
        else:
            aliases += [dict(alias=r["fighter1"], fighter_id=a1, source="betmma"),
                        dict(alias=r["fighter2"], fighter_id=a2, source="betmma")]
        winner = next((f for f, v in fs.items() if v["result"] == "win"), None)
        if winner and slug(r["result"]) and side(r["result"]) != winner:
            winner_mismatch += 1
        odds += [dict(bout_id=bid, bookmaker="betmma.tips", ts="", fighter_id=a1, price_decimal=o1, kind="unknown"),
                 dict(bout_id=bid, bookmaker="betmma.tips", ts="", fighter_id=a2, price_decimal=o2, kind="unknown")]
    stats.update(odds_rows=len(od_rows), odds_matched_exact=exact, odds_matched_fuzzy=fuzzy,
                 odds_unmatched=len(unmatched), odds_duplicate_for_bout=dup_odds,
                 odds_bad_price=bad_price, odds_winner_disagrees_with_result=winner_mismatch)

    # write ------------------------------------------------------------------------------
    stat_cols = ["kd", "sig_l", "td_l", "sub_att"]
    _write(out / "events.csv", list(events.values()), ["event_id", "name", "date", "city", "country", "venue"])
    _write(out / "fighters.csv", list(fighters.values()), ["fighter_id", "name", "dob", "height_cm", "reach_cm", "stance"])
    seen_al, uniq_al = set(), []
    for a in aliases:
        k = (a["alias"], a["fighter_id"])
        if k not in seen_al:
            seen_al.add(k)
            uniq_al.append(a)
    _write(out / "fighter_aliases.csv", uniq_al, ["alias", "fighter_id", "source"])
    _write(out / "bouts.csv", bouts, ["bout_id", "event_id", "weight_class", "is_title", "scheduled_rounds", "method",
                                      "method_detail", "end_round", "end_time_sec", "referee", "card_position"])
    _write(out / "bout_fighter.csv", bout_fighter, ["bout_id", "fighter_id", "corner", "result"])
    _write(out / "bout_totals.csv", totals, ["bout_id", "fighter_id"] + stat_cols)
    _write(out / "odds_snapshots.csv", odds, ["bout_id", "bookmaker", "ts", "fighter_id", "price_decimal", "kind"])
    if interim:
        _write(interim / "odds_unmatched.csv", unmatched, ["date", "event", "fighter1", "fighter2"])
    return stats
