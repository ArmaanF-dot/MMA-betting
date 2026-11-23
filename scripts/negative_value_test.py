"""Read-only question: what if we bet the model's pick even when the price says the bet has negative value (model probability x price - 1 < 0)?
Same 102 events with real sportsbook prices (2023-06 to 2025-10-18), the stack model's out-of-sample probabilities, 50 per event split
equally over the chosen picks (max 10 each), at the median price and the best price. Nothing in the system is changed."""
from collections import defaultdict
from statistics import median

import duckdb
import numpy as np

from ufcmodel.eval.betting_eval import MarketOfRecord

con = duckdb.connect("data/processed/ufc.duckdb", read_only=True)
mk = MarketOfRecord()
pred = dict(con.execute("SELECT bout_id, p_red FROM predictions_ml WHERE model = 'stack'").fetchall())
win = {b: c for b, c in con.execute("SELECT bout_id, corner FROM bout_fighter WHERE result = 'win'").fetchall()}
ev = {b: (e, str(d)) for b, e, d in con.execute("SELECT b.bout_id, b.event_id, e.date FROM bouts b JOIN events e USING (event_id)").fetchall()}
fights = defaultdict(list)
for b in pred:
    if b not in win or b not in ev or ev[b][1] < "2023-06-01":
        continue
    pr = mk.book_prices(b)
    if len(pr) < 3 or mk.close(b)[1] != "books":
        continue
    p = pred[b]
    red = p >= 0.5
    pp = p if red else 1 - p
    med = (median(a for a, _ in pr), median(c for _, c in pr))
    best = mk.best(b)
    fights[ev[b][0]].append(dict(pp=pp, won=(win[b] == "red") == red, med=med[0] if red else med[1], best=best[0] if red else best[1]))
events = [e for e, fs in fights.items() if len(fs) >= 4]
print(f"{len(events)} events, {sum(len(fights[e]) for e in events)} fights\n")
rng = np.random.default_rng(0)


def report(label, keep, price):
    per_p, per_s, n, hits = [], [], 0, 0
    for e in events:
        sel = [f for f in fights[e] if keep(f, price)]
        if not sel:
            continue
        stake = min(10.0, 50.0 / len(sel))
        per_p.append(sum(stake * (f[price] - 1) if f["won"] else -stake for f in sel))
        per_s.append(stake * len(sel))
        n += len(sel)
        hits += sum(f["won"] for f in sel)
    if not per_s:
        print(f"{label:58s} no bets")
        return
    p, s = np.array(per_p), np.array(per_s)
    ix = rng.integers(0, len(p), (4000, len(p)))
    roi = p[ix].sum(axis=1) / s[ix].sum(axis=1)
    print(f"{label:58s} {price:6s} events {len(p):3d} bets {n:4d} hit {hits/n:5.1%} staked {s.sum():6.0f} profit {p.sum():+8.1f} ROI {p.sum()/s.sum():+6.1%} [{np.percentile(roi,2.5):+.0%}, {np.percentile(roi,97.5):+.0%}]")


edge = lambda f, price: f["pp"] * f[price] - 1
for price in ("med", "best"):
    report("every model pick", lambda f, pr: True, price)
    report("picks with POSITIVE value (edge > 0)", lambda f, pr: edge(f, pr) > 0, price)
    report("picks with NEGATIVE value (edge < 0)", lambda f, pr: edge(f, pr) < 0, price)
    print()
print("Negative-value picks by how confident the model is in the pick (median price):")
for lo, hi in ((0.5, 0.6), (0.6, 0.7), (0.7, 1.01)):
    report(f"  negative value, model confidence {lo:.0%} to {min(hi, 1):.0%}", lambda f, pr, lo=lo, hi=hi: edge(f, pr) < 0 and lo <= f["pp"] < hi, "med")
print("\nSame, best price:")
for lo, hi in ((0.5, 0.6), (0.6, 0.7), (0.7, 1.01)):
    report(f"  negative value, model confidence {lo:.0%} to {min(hi, 1):.0%}", lambda f, pr, lo=lo, hi=hi: edge(f, pr) < 0 and lo <= f["pp"] < hi, "best")
