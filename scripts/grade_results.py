"""Grade finished cards against the real results and write data/paper/results.json (read by scripts/signal_data.py for the page).
For each card with saved predictions whose date has passed and whose fights are in the results data:
  - per fight: the winner, the method and round, and what the model alone, the blend, the market and Elo each picked, with log loss and Brier
  - accuracy of each with a 95% interval (Wilson), calibration buckets for the model's picks, and who was right when the model and market disagreed
  - the staking rule's bets from the ledger (frozen at the last export before the card), at the 50 budget and the 1,000 budget scale
  - the paper-test picks (70%+ confident, flat 10 at the best price) from data/paper/confident_picks.csv
Predictions used are the LAST capture before the card (the latest slot), so prices and probabilities are what was on offer then.
A card is graded only when every fight in its predictions has a result; otherwise it waits. Read-only except the output file."""
import csv
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

from ufcmodel.ingest.bfo import _lookup, norm

SCALE = 1000.0 / 50.0
con = duckdb.connect("data/processed/ufc.duckdb", read_only=True)
alias = _lookup(con)
today = date.today().isoformat()
ledger = json.loads(Path("data/paper/ledger.json").read_text(encoding="utf-8")) if Path("data/paper/ledger.json").exists() else {}
picks_rows = list(csv.DictReader(open("data/paper/confident_picks.csv", encoding="utf-8"))) if Path("data/paper/confident_picks.csv").exists() else []


def outcome(a, b, d):
    """(winner name or None, method, round) for fighters a and b around date d, from the results data; ('void',...) for a draw or no contest."""
    fa, fb = alias.get(norm(a)), alias.get(norm(b))
    if not (fa and fb):
        return None
    d0 = date.fromisoformat(d)
    row = con.execute("""SELECT x.result, b.method, b.end_round FROM bout_fighter x JOIN bout_fighter y ON y.bout_id = x.bout_id AND y.fighter_id = ?
                         JOIN bouts b ON b.bout_id = x.bout_id JOIN events e ON e.event_id = b.event_id
                         WHERE x.fighter_id = ? AND e.date BETWEEN ? AND ? LIMIT 1""", [fb, fa, d0 - timedelta(days=3), d0 + timedelta(days=3)]).fetchone()
    if not row:
        return None
    return (a if row[0] == "win" else (b if row[0] == "loss" else "void")), row[1], row[2]


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (round(c - h, 4), round(c + h, 4))


cards = []
for f in sorted(Path("data/paper").glob("predictions_*.csv")):
    ev_date = f.stem.split("_")[1]
    if ev_date >= today:
        continue
    rows = list(csv.DictReader(open(f, encoding="utf-8")))
    last = {}
    for r in sorted(rows, key=lambda r: r["ts"]):
        last[(r["fighter_a"], r["fighter_b"])] = r             # latest capture per fight
    fights, missing = [], []
    for (a, b), r in last.items():
        res = outcome(a, b, ev_date)
        if res is None:
            missing.append(f"{a} vs {b}")                    # cancelled, or not in the results data yet: shown, not scored
            continue
        winner, method, rnd = res
        pm = float(r["p_a_model_no_market"]); pb = float(r["p_a_blend"]); pe = float(r["p_a_elo"])
        pk = float(r["p_a_market_devig"]) if r["p_a_market_devig"] else None
        fights.append(dict(a=a, b=b, winner=winner, method=method, round=rnd, slot=r["slot"], p_model=pm, p_blend=pb, p_elo=pe, p_mkt=pk,
                           best_a=float(r["best_a"]) if r["best_a"] else None, best_b=float(r["best_b"]) if r["best_b"] else None))
    if not fights:
        print(f"{ev_date}: no results yet; not graded")
        continue
    graded = [x for x in fights if x["winner"] != "void"]
    for x in fights:
        if x["winner"] == "void":
            x["scored"] = False
            continue
        ya = 1.0 if x["winner"] == x["a"] else 0.0
        x["scored"] = True
        for k in ("model", "blend", "elo", "mkt"):
            p = x["p_" + k]
            x["pick_" + k] = None if p is None else (x["a"] if p >= 0.5 else x["b"])
            x["ok_" + k] = None if p is None else ((p >= 0.5) == (ya == 1.0))
            x["ll_" + k] = None if p is None else -math.log(max(1e-6, min(1 - 1e-6, p if ya == 1.0 else 1 - p)))
            x["br_" + k] = None if p is None else (p - ya) ** 2
        x["conf_model"] = max(x["p_model"], 1 - x["p_model"])
    n = len(graded)

    def acc(k, only=None):
        xs = [x for x in graded if x["ok_" + k] is not None and (only is None or only(x))]
        return dict(k=sum(1 for x in xs if x["ok_" + k]), n=len(xs), ci=wilson(sum(1 for x in xs if x["ok_" + k]), len(xs)))

    def avg(key, only=None):
        xs = [x[key] for x in graded if x.get(key) is not None and (only is None or only(x))]
        return round(sum(xs) / len(xs), 4) if xs else None
    both = lambda x: x["p_mkt"] is not None
    stats = dict(n=n, model=acc("model"), blend=acc("blend"), elo=acc("elo"), market=acc("mkt"),
                 ll=dict(model=avg("ll_model", both), blend=avg("ll_blend", both), market=avg("ll_mkt", both), elo=avg("ll_elo", both), coin=0.6931),
                 brier=dict(model=avg("br_model", both), blend=avg("br_blend", both), market=avg("br_mkt", both), elo=avg("br_elo", both)),
                 priced=sum(1 for x in graded if both(x)))
    dis = [x for x in graded if x["p_mkt"] is not None and x["pick_model"] != x["pick_mkt"]]
    stats["disagree"] = dict(n=len(dis), model_right=sum(1 for x in dis if x["ok_model"]), market_right=sum(1 for x in dis if x["ok_mkt"]))
    stats["buckets"] = []
    for lo, hi, name in ((0.5, 0.6, "50-60%"), (0.6, 0.7, "60-70%"), (0.7, 1.01, "70%+")):
        xs = [x for x in graded if lo <= x["conf_model"] < hi]
        stats["buckets"].append(dict(name=name, n=len(xs), hit=sum(1 for x in xs if x["ok_model"]), said=round(sum(x["conf_model"] for x in xs) / len(xs), 4) if xs else None))
    # staking-rule bets from the ledger
    led = next((v for v in ledger.values() if v["date"] == ev_date or v["date"] in (ev_date, str(date.fromisoformat(ev_date) + timedelta(days=1)))), None)
    bets = []
    for b in (led["bets"] if led else []):
        r = outcome(b["fighter"], b["vs"], ev_date)
        st = None if r is None else ("won" if r[0] == b["fighter"] else ("lost" if r[0] != "void" else "void"))
        pnl = 0.0 if st in (None, "void") else (b["stake"] * (b["price"] - 1) if st == "won" else -b["stake"])
        bets.append(dict(b, status=st, pnl=round(pnl, 2), pnl_1000=round(pnl * SCALE, 2), stake_1000=round(b["stake"] * SCALE, 2)))
    # paper-test picks
    seen, picks = {}, []
    for r in picks_rows:
        if r["date"][:10] == (led or {}).get("date", ev_date) or r["date"][:10] == ev_date:
            seen[r["pick"]] = r
    for p, r in seen.items():
        o = outcome(p, r["opponent"], ev_date)
        st = None if o is None else ("won" if o[0] == p else ("lost" if o[0] != "void" else "void"))
        price = float(r["best_price"]); pnl = 0.0 if st in (None, "void") else (10 * (price - 1) if st == "won" else -10.0)
        picks.append(dict(fighter=p, vs=r["opponent"], conf=float(r["model_p_pick"]), tier=r["tier"], price=price, book=r["best_book"], status=st, pnl=round(pnl, 2)))
    cards.append(dict(date=ev_date, name=(led or {}).get("name", "UFC " + ev_date), slot=max((x["slot"] for x in fights), key=lambda s: ["manual", "listed", "mon", "thu", "pre"].index(s) if s in ["manual", "listed", "mon", "thu", "pre"] else 0),
                      fights=fights, missing=missing, stats=stats, bets=bets, picks=picks,
                      bets_summary=dict(n=len(bets), won=sum(1 for b in bets if b["status"] == "won"), staked=round(sum(b["stake"] for b in bets), 2), pnl=round(sum(b["pnl"] for b in bets), 2),
                                        pnl_1000=round(sum(b["pnl_1000"] for b in bets), 2), staked_1000=round(sum(b["stake_1000"] for b in bets), 2)),
                      picks_summary=dict(n=len(picks), won=sum(1 for p in picks if p["status"] == "won"), pnl=round(sum(p["pnl"] for p in picks), 2))))
    print(f"{ev_date}: graded {n} fights ({len(fights) - n} void); model {stats['model']['k']}/{stats['model']['n']}, market {stats['market']['k']}/{stats['market']['n']}, blend {stats['blend']['k']}/{stats['blend']['n']}, elo {stats['elo']['k']}/{stats['elo']['n']}")

out = dict(asof=datetime.now().isoformat(timespec="minutes"), cards=cards)
Path("data/paper/results.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print(f"wrote data/paper/results.json with {len(cards)} graded card(s)")
