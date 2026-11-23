"""GBP 50 per event, split across the fights by a fixed rule, replayed on the last 30 events that have real sportsbook prices and an
out-of-sample prediction (the locked holdout is not used, so the sim ends 2025-10-18). Moneylines only. The bankroll resets to 50
each event. Rules are fixed here, before the run:
  equal-pick  : 50 split equally over every fight, on the model's pick, median price
  equal-fav   : 50 split equally over every fight, on the market favourite, median price
  kelly-model : quarter Kelly on the stack model's probability, best sportsbook price, edge > 0, max 10 per fight, scaled to 50 in total
  kelly-blend : the same with a 50/50 blend of model and market probability (shrinks the claimed edge)
  kelly-model-median / kelly-blend-median : the same two at the median price (no line shopping)"""
from collections import defaultdict
from statistics import median

import duckdb
import numpy as np

from ufcmodel.eval.betting_eval import MarketOfRecord, flat_returns

BANK, CAP, KAPPA = 50.0, 10.0, 0.25
con = duckdb.connect("data/processed/ufc.duckdb", read_only=True)
mk = MarketOfRecord()
pred = dict(con.execute("SELECT bout_id, p_red FROM predictions_ml WHERE model = 'stack'").fetchall())
win = {b: (f, c) for b, f, c in con.execute("SELECT bout_id, fighter_id, corner FROM bout_fighter WHERE result = 'win'").fetchall()}
ev = {b: (e, str(d), n) for b, e, d, n in con.execute("SELECT b.bout_id, b.event_id, e.date, e.name FROM bouts b JOIN events e USING (event_id)").fetchall()}
fights = defaultdict(list)
for b in pred:
    if b not in win or b not in ev:
        continue
    pr = mk.book_prices(b)
    p_mkt, src = mk.close(b)
    if len(pr) < 3 or src != "books":
        continue
    red_won = win[b][1] == "red"
    fights[ev[b][0]].append(dict(b=b, p=pred[b], pm=p_mkt, med=(median(a for a, _ in pr), median(c for _, c in pr)), best=mk.best(b), red_won=red_won))
events = sorted([e for e, fs in fights.items() if len(fs) >= 4], key=lambda e: ev[fights[e][0]["b"]][1])[-30:]
print(f"{len(events)} events, {ev[fights[events[0]][0]['b']][1]} to {ev[fights[events[-1]][0]['b']][1]}, fights per event {min(len(fights[e]) for e in events)}-{max(len(fights[e]) for e in events)}")


def side_won(f, red):
    return f["red_won"] if red else not f["red_won"]


def equal(pick):
    def rule(fs):
        out = []
        for f in fs:
            red = (f["p"] >= 0.5) if pick == "model" else (f["pm"] >= 0.5)
            out.append((BANK / len(fs), f["med"][0] if red else f["med"][1], side_won(f, red)))
        return out
    return rule


def kelly(prob, price):
    def rule(fs):
        cand = []
        for f in fs:
            p = f["p"] if prob == "model" else 0.5 * f["p"] + 0.5 * f["pm"]
            pr = f["best"] if price == "best" else f["med"]
            for red, pp, o in ((True, p, pr[0]), (False, 1 - p, pr[1])):
                if pp * o - 1 > 0:
                    cand.append((min(CAP, KAPPA * (pp * o - 1) / (o - 1) * BANK), o, side_won(f, red)))
        tot = sum(c[0] for c in cand)
        s = min(1.0, BANK / tot) if tot > 0 else 0.0
        return [(st * s, o, w) for st, o, w in cand]
    return rule


rules = {"equal-pick": equal("model"), "equal-fav": equal("fav"), "kelly-model": kelly("model", "best"), "kelly-blend": kelly("blend", "best"),
         "kelly-model-median": kelly("model", "med"), "kelly-blend-median": kelly("blend", "med")}
print(f"\n{'rule':20s} {'staked':>8s} {'profit':>9s} {'ROI':>7s} {'bets/ev':>8s} {'winning events':>15s} {'worst event':>12s} {'best event':>11s}  ROI 95% (events as units)")
for name, rule in rules.items():
    per, staked, nb, prof, evs = [], 0.0, 0, [], []
    for e in events:
        bets = rule(fights[e])
        pnl = sum(st * (o - 1) if w else -st for st, o, w in bets)
        per.append(pnl)
        staked += sum(st for st, _, _ in bets)
        nb += len(bets)
        prof += [st * (o - 1) if w else -st for st, o, w in bets]
        evs += [e] * len(bets)
    r = flat_returns(prof, evs, stake=1.0) if prof else dict(lo=0, hi=0)
    # event-level interval on ROI of staked money, bootstrap over events
    rng = np.random.default_rng(0)
    st_e = np.array([sum(s for s, _, _ in rule(fights[e])) for e in events])
    pn = np.array(per)
    idx = rng.integers(0, len(events), (4000, len(events)))
    roi = pn[idx].sum(axis=1) / np.maximum(st_e[idx].sum(axis=1), 1e-9)
    print(f"{name:20s} {staked:8.0f} {sum(per):+9.2f} {sum(per)/staked:+7.1%} {nb/len(events):8.1f} {sum(p > 0 for p in per):>10d}/{len(events)} {min(per):+12.2f} {max(per):+11.2f}  [{np.percentile(roi,2.5):+.0%}, {np.percentile(roi,97.5):+.0%}]")
print("\nStandard deviation of one event's result (equal-pick):", f"{np.std([sum(st * (o - 1) if w else -st for st, o, w in rules['equal-pick'](fights[e])) for e in events]):.2f}", "pounds")
