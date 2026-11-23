"""Replication of parlay_hedge_test.py on EARLIER years (2017-01 to 2023-05): same structures, same legs (the most confident model picks),
prices from the fighter pages' closing range: 'mid' (typical) = the average of the lowest and highest closing price for the side,
'best' = the highest. Parlay = product of the single mid prices. Read-only."""
from collections import defaultdict
from itertools import combinations

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
    o = mk.oc.get(b)
    if b not in win or b not in ev or not ("2017-01-01" <= ev[b][1] < "2023-06-01") or not o or not all(o[k] for k in ("low_red", "high_red", "low_blue", "high_blue")):
        continue
    red = pred[b] >= 0.5
    own = (o["low_red"], o["high_red"]) if red else (o["low_blue"], o["high_blue"])
    oth = (o["low_blue"], o["high_blue"]) if red else (o["low_red"], o["high_red"])
    fights[ev[b][0]].append(dict(pp=pred[b] if red else 1 - pred[b], won=(win[b] == "red") == red, med=sum(own) / 2, best=own[1], opp=sum(oth) / 2))
events = [e for e, fs in fights.items() if len(fs) >= 4]
rng = np.random.default_rng(0)
top = lambda e, n: sorted(fights[e], key=lambda f: -f["pp"])[:n]
parlay = lambda legs, stake, price="med": stake * (np.prod([f[price] for f in legs]) - 1) if all(f["won"] for f in legs) else -stake
singles = lambda legs, stake, price="med": sum(stake * (f[price] - 1) if f["won"] else -stake for f in legs)


def structure(name, e):
    t4 = top(e, 4)
    return {"singles": lambda: singles(t4, 12.5), "parlay 3": lambda: parlay(top(e, 3), 50), "parlay 4": lambda: parlay(t4, 50),
            "parlay + singles": lambda: parlay(t4, 25) + singles(t4, 6.25),
            "parlay + insurance": lambda: parlay(t4, 35) + sum(3.75 * (f["opp"] - 1) if not f["won"] else -3.75 for f in t4),
            "yankee": lambda: sum(parlay(list(c), 50 / 11) for k in (2, 3, 4) for c in combinations(t4, k)),
            "parlay 4, high-end price legs": lambda: parlay(t4, 50, "best")}[name]()


print(f"{len(events)} events, 2017-01 to 2023-05; legs average {np.mean([f['pp'] for e in events for f in top(e, 4)]):.0%} model confidence, hit {np.mean([f['won'] for e in events for f in top(e, 4)]):.0%}\n")
print(f"{'structure':30s} {'staked':>7s} {'profit':>9s} {'ROI':>7s} {'95% (events)':>14s} {'events up':>10s} {'worst':>8s} {'best':>8s} {'sd/event':>9s}")
for name in ("singles", "parlay 3", "parlay 4", "parlay + singles", "parlay + insurance", "yankee", "parlay 4, high-end price legs"):
    pnl = np.array([structure(name, e) for e in events])
    ix = rng.integers(0, len(pnl), (4000, len(pnl)))
    roi = pnl[ix].sum(axis=1) / (50.0 * len(pnl))
    print(f"{name:30s} {50 * len(pnl):7.0f} {pnl.sum():+9.1f} {pnl.sum()/(50*len(pnl)):+7.1%} [{np.percentile(roi,2.5):+5.0%},{np.percentile(roi,97.5):+5.0%}] {int((pnl > 0).sum()):>5d}/{len(pnl)} {pnl.min():+8.1f} {pnl.max():+8.1f} {pnl.std():9.1f}")
