"""Read-only: parlays with hedges as 'risk management'. GBP 50 per event, the model's most confident picks as legs, real sportsbook prices
(2023-06 to 2025-10-18, 102 events, stack model out of sample). A parlay pays the product of its legs' single prices (an assumption: books
often shave parlays further, so this flatters them); legs use the median price (one book) unless marked best. Structures fixed here:
  singles        top 4 picks, 12.50 each
  parlay 3 / 4   all 50 on the 3 or 4 most confident picks
  parlay + singles   25 on the 4-leg parlay, 25 spread as singles on the same 4 picks
  parlay + insurance 35 on the 4-leg parlay, 15 spread on the OTHER side of the same 4 fights (pays when a leg loses)
  yankee         top 4: 6 doubles + 4 trebles + 1 fourfold, 50 spread equally over the 11 bets (pays on any 2 correct)
  parlay 4, best price legs  the 4-leg parlay with every leg at its best price (not possible at one book: an upper bound)"""
from collections import defaultdict
from itertools import combinations
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
    red = pred[b] >= 0.5
    med = (median(a for a, _ in pr), median(c for _, c in pr))
    best = mk.best(b)
    i, j = (0, 1) if red else (1, 0)
    fights[ev[b][0]].append(dict(pp=pred[b] if red else 1 - pred[b], won=(win[b] == "red") == red, med=med[i], best=best[i], opp=med[j]))
events = [e for e, fs in fights.items() if len(fs) >= 4]
rng = np.random.default_rng(0)


def top(e, n):
    return sorted(fights[e], key=lambda f: -f["pp"])[:n]


def parlay(legs, stake, price="med"):
    prod = np.prod([f[price] for f in legs])
    return stake * (prod - 1) if all(f["won"] for f in legs) else -stake


def singles(legs, stake, price="med"):
    return sum(stake * (f[price] - 1) if f["won"] else -stake for f in legs)


def structure(name, e):
    t4 = top(e, 4)
    if name == "singles":
        return singles(t4, 12.5)
    if name == "parlay 3":
        return parlay(top(e, 3), 50)
    if name == "parlay 4":
        return parlay(t4, 50)
    if name == "parlay + singles":
        return parlay(t4, 25) + singles(t4, 6.25)
    if name == "parlay + insurance":
        return parlay(t4, 35) + sum(3.75 * (f["opp"] - 1) if not f["won"] else -3.75 for f in t4)
    if name == "yankee":
        combos = [c for k in (2, 3, 4) for c in combinations(t4, k)]
        return sum(parlay(list(c), 50 / 11) for c in combos)
    if name == "parlay 4, best price legs":
        return parlay(t4, 50, "best")


print(f"{len(events)} events; legs are the most confident picks (their model confidence averages {np.mean([f['pp'] for e in events for f in top(e, 4)]):.0%}, hit {np.mean([f['won'] for e in events for f in top(e, 4)]):.0%})\n")
print(f"{'structure':28s} {'staked':>7s} {'profit':>9s} {'ROI':>7s} {'95% (events)':>14s} {'events up':>10s} {'worst event':>12s} {'best event':>11s} {'sd per event':>13s}")
for name in ("singles", "parlay 3", "parlay 4", "parlay + singles", "parlay + insurance", "yankee", "parlay 4, best price legs"):
    pnl = np.array([structure(name, e) for e in events])
    ix = rng.integers(0, len(pnl), (4000, len(pnl)))
    roi = pnl[ix].sum(axis=1) / (50.0 * len(pnl))
    print(f"{name:28s} {50 * len(pnl):7.0f} {pnl.sum():+9.1f} {pnl.sum()/(50*len(pnl)):+7.1%} [{np.percentile(roi,2.5):+5.0%},{np.percentile(roi,97.5):+5.0%}] {int((pnl > 0).sum()):>5d}/{len(pnl)} {pnl.min():+12.1f} {pnl.max():+11.1f} {pnl.std():13.1f}")
