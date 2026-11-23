"""Bankroll rules on every event with real sportsbook prices and an out-of-sample prediction (2023-06 to 2025-10-18; the locked
holdout is not used; earlier years only have the old margin-free price file, which would flatter any rule). Moneylines only.
Rules fixed before the run:
  event budget: 50 reset each event, or compounding (start 250, each event risks 20% of the current bankroll)
  p*        : sigmoid(w logit(stack model) + (1-w) logit(market)); w is the blend weight the stack fit chose on EARLIER folds (stack.json)
  bet       : a side only if p* x price - 1 > 3%; stake = quarter Kelly x budget, halved if either fighter has fewer than 3 earlier UFC
              fights, halved again if |p* - market| > 0.15; max 20% of the budget per fight; scaled down to the budget in total
  price     : best sportsbook price (line shopping) or the median price
Comparison rules: the earlier 'kelly-model' (pure model, edge > 0, no sizing adjustments), equal split on the pick, equal split on favourites."""
import json
from collections import defaultdict
from statistics import median

import duckdb
import numpy as np

from ufcmodel.eval.betting_eval import MarketOfRecord

KAPPA, EDGE, CAPF = 0.25, 0.03, 0.20
con = duckdb.connect("data/processed/ufc.duckdb", read_only=True)
mk = MarketOfRecord()
stack = json.load(open("data/processed/stack.json"))
W = {k: v[0] for k, v in stack.items()}
pred = dict(con.execute("SELECT bout_id, p_red FROM predictions_ml WHERE model = 'stack'").fetchall())
win = {b: c for b, c in con.execute("SELECT bout_id, corner FROM bout_fighter WHERE result = 'win'").fetchall()}
ev = {b: (e, str(d)) for b, e, d in con.execute("SELECT b.bout_id, b.event_id, e.date FROM bouts b JOIN events e USING (event_id)").fetchall()}
prior = {}
for b, f, n in con.execute("""SELECT bf.bout_id, bf.fighter_id, row_number() OVER (PARTITION BY bf.fighter_id ORDER BY e.date, bf.bout_id) - 1
                              FROM bout_fighter bf JOIN bouts b USING (bout_id) JOIN events e USING (event_id)""").fetchall():
    prior[(b, f)] = n
lg = lambda p: np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))
sg = lambda z: 1 / (1 + np.exp(-z))
fights = defaultdict(list)
for b in pred:
    if b not in win or b not in ev or ev[b][1] < "2023-06-01":
        continue
    pr = mk.book_prices(b)
    p_mkt, src = mk.close(b)
    if len(pr) < 3 or src != "books":
        continue
    w = W.get(ev[b][1][:4], 0.5)
    fights[ev[b][0]].append(dict(
        b=b, p=pred[b], pm=p_mkt, ps=float(sg(w * lg(pred[b]) + (1 - w) * lg(p_mkt))),
        med=(median(a for a, _ in pr), median(c for _, c in pr)), best=mk.best(b), red_won=win[b] == "red",
        thin=min(prior.get((b, mk.red[b]), 0), prior.get((b, mk.blue[b]), 0)) < 3))
events = sorted([e for e, fs in fights.items() if len(fs) >= 4], key=lambda e: ev[fights[e][0]["b"]][1])
print(f"{len(events)} events, {ev[fights[events[0]][0]['b']][1]} to {ev[fights[events[-1]][0]['b']][1]}, {sum(len(fights[e]) for e in events)} fights")


def won(f, red):
    return f["red_won"] if red else not f["red_won"]


def equal(kind):
    def rule(fs, budget):
        out = []
        for f in fs:
            red = (f["p"] >= 0.5) if kind == "pick" else (f["pm"] >= 0.5)
            out.append((budget / len(fs), f["med"][0] if red else f["med"][1], won(f, red)))
        return out
    return rule


def kelly(prob, price, adjust, edge=0.0):
    def rule(fs, budget):
        cand = []
        for f in fs:
            p = f["p"] if prob == "model" else f["ps"]
            pr = f["best"] if price == "best" else f["med"]
            for red, pp, o in ((True, p, pr[0]), (False, 1 - p, pr[1])):
                if pp * o - 1 > edge:
                    m = 1.0
                    if adjust:
                        m *= 0.5 if f["thin"] else 1.0
                        m *= 0.5 if abs(pp - (f["pm"] if red else 1 - f["pm"])) > 0.15 else 1.0
                    cand.append((min(CAPF * budget, KAPPA * (pp * o - 1) / (o - 1) * budget * m), o, won(f, red)))
        tot = sum(c[0] for c in cand)
        s = min(1.0, budget / tot) if tot > 0 else 0.0
        return [(st * s, o, w) for st, o, w in cand]
    return rule


RULES = [("equal split, model pick (median)", equal("pick"), False), ("equal split, favourite (median)", equal("fav"), False),
         ("old: pure model Kelly, best price", kelly("model", "best", False), False),
         ("shrink to market only, best price", kelly("blend", "best", False), False),
         ("full rule, best price (reset 50)", kelly("blend", "best", True, EDGE), False),
         ("full rule, median price (reset 50)", kelly("blend", "med", True, EDGE), False),
         ("full rule, best price (compounding)", kelly("blend", "best", True, EDGE), True)]
rng = np.random.default_rng(0)
print(f"\n{'rule':40s} {'staked':>8s} {'profit':>9s} {'ROI':>7s} {'bets/ev':>8s} {'events +':>9s}  ROI 95% (events as units)   final bankroll / max drawdown")
for name, rule, compound in RULES:
    bank, peak, mdd, per, st_e = 250.0, 250.0, 0.0, [], []
    for e in events:
        budget = max(0.0, 0.2 * bank) if compound else 50.0
        bets = rule(fights[e], budget)
        pnl = sum(st * (o - 1) if w else -st for st, o, w in bets)
        per.append(pnl)
        st_e.append(sum(s for s, _, _ in bets))
        if compound:
            bank += pnl
            peak = max(peak, bank)
            mdd = max(mdd, (peak - bank) / peak)
    per, st_e = np.array(per), np.array(st_e)
    idx = rng.integers(0, len(events), (4000, len(events)))
    roi = per[idx].sum(axis=1) / np.maximum(st_e[idx].sum(axis=1), 1e-9)
    extra = f"{bank:7.0f} / {mdd:.0%}" if compound else ""
    nb = np.mean([len(rule(fights[e], 50.0)) for e in events])
    print(f"{name:40s} {st_e.sum():8.0f} {per.sum():+9.2f} {per.sum()/st_e.sum():+7.1%} {nb:8.1f} {int((per > 0).sum()):>5d}/{len(events)}  [{np.percentile(roi,2.5):+.0%}, {np.percentile(roi,97.5):+.0%}]   {extra}")
