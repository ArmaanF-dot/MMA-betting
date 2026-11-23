"""Replication of the confidence-cutoff test on EARLIER years (2017-01 to 2023-05), which the first look did not use. Prices come from the
fighter pages' closing range (lowest and highest closing price for the side across books): 'mid' = the average of the two (a typical
price), 'high' = the highest (best price). Stack model, 50 per event split equally (max 10 each). Read-only."""
from collections import defaultdict

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
    lo, hi = (o["low_red"], o["high_red"]) if red else (o["low_blue"], o["high_blue"])
    pc, _ = mk.close(b)
    fights[ev[b][0]].append(dict(pp=pred[b] if red else 1 - pred[b], mk=pc if red else 1 - pc, won=(win[b] == "red") == red, mid=(lo + hi) / 2, high=hi))
events = [e for e, fs in fights.items() if len(fs) >= 4]
rng = np.random.default_rng(0)
print(f"{len(events)} events, {sum(len(fights[e]) for e in events)} fights, 2017-01 to 2023-05\n")
print(f"{'cutoff':>7s} {'price':>6s} {'bets':>5s} {'events':>6s} {'hit':>6s} {'model says':>10s} {'market says':>11s} {'mean price':>10s} {'staked':>7s} {'profit':>8s} {'ROI':>7s}  95%")
for cut in (0.50, 0.70, 0.75, 0.80, 0.85):
    for price in ("mid", "high"):
        pp_, ps_, n, hits, mods, mks, prices = [], [], 0, 0, [], [], []
        for e in events:
            sel = [f for f in fights[e] if f["pp"] >= cut]
            if not sel:
                continue
            stake = min(10.0, 50.0 / len(sel))
            pp_.append(sum(stake * (f[price] - 1) if f["won"] else -stake for f in sel))
            ps_.append(stake * len(sel))
            n += len(sel)
            hits += sum(f["won"] for f in sel)
            mods += [f["pp"] for f in sel]
            mks += [f["mk"] for f in sel]
            prices += [f[price] for f in sel]
        if not ps_:
            continue
        p, s = np.array(pp_), np.array(ps_)
        ix = rng.integers(0, len(p), (4000, len(p)))
        roi = p[ix].sum(axis=1) / s[ix].sum(axis=1)
        print(f"{cut:7.0%} {price:>6s} {n:5d} {len(p):6d} {hits/n:6.1%} {np.mean(mods):10.1%} {np.mean(mks):11.1%} {np.mean(prices):10.2f} {s.sum():7.0f} {p.sum():+8.1f} {p.sum()/s.sum():+7.1%}  [{np.percentile(roi,2.5):+.0%}, {np.percentile(roi,97.5):+.0%}]")
