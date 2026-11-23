"""The two frozen candidate strategies from Stage 3 on past events with GBP 50 per event (reset each event), out of sample only:
  C2 (H4): p = sigmoid(logit(market close) + features x discovery coefficients); both sides, a side is bet when p x price - 1 > 3%;
           stake = quarter Kelly x 50, at most 10 per fight, scaled to 50 in total. Per-book prices, so 2023-06 to 2025-10-24.
           Best sportsbook price, and the median price (no line shopping). The comparison row uses the market's own probability
           in place of p (line shopping alone).
  C1 (H3): bet at the OPENING price on the side the model likes more than the open does, when the predicted move
           beta x (logit(model) - logit(open)) exceeds 0.05 logit; beta is the discovery (2015-2021) estimate, 0.1698, so 2022 on is out
           of sample; 50 split equally over the selected bets, at most 10 each.
Events are the units for intervals. The locked holdout is not used."""
import pickle
from collections import defaultdict
from statistics import median

import numpy as np

from ufcmodel.eval.betting_eval import MarketOfRecord, clv

S = pickle.load(open("data/processed/stage3.pkl", "rb"))
data, b11, mean, sd = S["data"], S["b11"], S["mean11"], S["sd11"]
lg = lambda p: np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))
mk = MarketOfRecord()
BANK, CAP, KAPPA, EDGE, BETA = 50.0, 10.0, 0.25, 0.03, 0.1698


def summarize(name, per_event, extra=""):
    ev = sorted(per_event)
    pnl = np.array([per_event[e][0] for e in ev])
    stk = np.array([per_event[e][1] for e in ev])
    rng = np.random.default_rng(0)
    ix = rng.integers(0, len(ev), (4000, len(ev)))
    roi = pnl[ix].sum(axis=1) / np.maximum(stk[ix].sum(axis=1), 1e-9)
    nb = sum(per_event[e][2] for e in ev)
    print(f"{name:46s} events {len(ev):3d}  bets {nb:5d}  staked {stk.sum():7.0f}  profit {pnl.sum():+8.2f}  ROI {pnl.sum()/stk.sum():+6.1%} [{np.percentile(roi,2.5):+.0%}, {np.percentile(roi,97.5):+.0%}]  events in profit {int((pnl>0).sum())}/{int((stk>0).sum())}  {extra}", flush=True)
    return pnl, stk


def by_event_kelly(fights, probs, price):
    res = defaultdict(list)
    for x, p in zip(fights, probs):
        bp = mk.best(x["b"]) if price == "best" else (median(a for a, _ in mk.book_prices(x["b"])), median(c for _, c in mk.book_prices(x["b"])))
        for red, pp, o in ((True, p, bp[0]), (False, 1 - p, bp[1])):
            if pp * o - 1 > EDGE:
                res[x["e"]].append((min(CAP, KAPPA * (pp * o - 1) / (o - 1) * BANK), o, (x["y"] == 1.0) == red, x["d"], clv(o, x["pc"] if red else 1 - x["pc"])))
    out, years = {}, defaultdict(lambda: [0.0, 0.0])
    cl = []
    for e, bets in res.items():
        tot = sum(b[0] for b in bets)
        s = min(1.0, BANK / tot)
        pnl = sum(b[0] * s * (b[1] - 1) if b[2] else -b[0] * s for b in bets)
        out[e] = (pnl, tot * s, len(bets))
        years[bets[0][3][:4]][0] += pnl
        years[bets[0][3][:4]][1] += tot * s
        cl += [b[4] for b in bets]
    return out, {y: v for y, v in sorted(years.items())}, float(np.mean(cl)) if cl else float("nan")


print("== C2 (H4 market-residual model), per-book prices, 2023-06 to 2025-10-24 ==")
val = [x for x in data if x["d"] >= "2023-06-01" and len(mk.book_prices(x["b"])) >= 3]
F = np.array([x["f"] for x in val], float)
p_h4 = 1 / (1 + np.exp(-(np.array([lg(x["pc"]) for x in val]) + ((F - mean) / sd) @ b11)))
p_mkt = np.array([x["pc"] for x in val])
print(f"{len({x['e'] for x in val})} events, {len(val)} fights")
for label, probs, price in (("H4, best price", p_h4, "best"), ("H4, median price", p_h4, "median"),
                            ("market only (line shopping), best price", p_mkt, "best")):
    per, yrs, cl = by_event_kelly(val, probs, price)
    summarize(label, per, f"mean CLV {cl:+.3f}")
    print("      by year:", ", ".join(f"{y}: {v[0]:+.1f} on {v[1]:.0f}" for y, v in yrs.items()))

print("\n== C1 (H3 opening-line rule), opening prices, 2022-01-01 to 2025-10-24, beta from discovery only ==")
res, cl = defaultdict(list), []
for x in data:
    if x["d"] < "2022-01-01" or x["po"] is None or x["pc_oc"] is None or not x["red_price"] or not x["blue_price"]:
        continue
    mv = BETA * (lg(x["model"]) - lg(x["po"]))
    if abs(mv) <= 0.05:
        continue
    red = mv > 0
    price = x["red_price"] if red else x["blue_price"]
    res[x["e"]].append((price, (x["y"] == 1.0) == red, x["d"][:4]))
    cl.append(clv(price, x["pc_oc"] if red else 1 - x["pc_oc"]))
per, years = {}, defaultdict(lambda: [0.0, 0.0])
for e, bets in res.items():
    stake = min(CAP, BANK / len(bets))
    pnl = sum(stake * (p - 1) if w else -stake for p, w, _ in bets)
    per[e] = (pnl, stake * len(bets), len(bets))
    years[bets[0][2]][0] += pnl
    years[bets[0][2]][1] += stake * len(bets)
summarize("H3 opening-line rule", per, f"mean CLV {np.mean(cl):+.3f}")
print("      by year:", ", ".join(f"{y}: {v[0]:+.1f} on {v[1]:.0f}" for y, v in sorted(years.items())))
