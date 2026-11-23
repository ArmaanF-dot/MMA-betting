"""Is the H3 opening-line result the model, or just the favourite bias at the open? Same period (2022-01-01 to 2025-10-24), same
opening prices, 50 per event split equally (max 10 each). Rows:
  all favourites at the open (no model)          every fight, the side the opening line makes the favourite
  H3 rule, favourite sides only / underdog sides only   the same bets as C1, split by whether the chosen side was the open favourite
  model's pick at the open, every fight (no threshold)
  H3 rule vs the same count of random sides of those fights (shuffled 200 times): how often chance does as well"""
from collections import defaultdict

import numpy as np

S = __import__("pickle").load(open("data/processed/stage3.pkl", "rb"))
data = [x for x in S["data"] if x["d"] >= "2022-01-01" and x["po"] is not None and x["pc_oc"] is not None and x["red_price"] and x["blue_price"]]
lg = lambda p: np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))
BETA = 0.1698


def run(name, pick):
    """pick(x) -> None or True (red) / False (blue)."""
    ev = defaultdict(list)
    for x in data:
        s = pick(x)
        if s is None:
            continue
        price = x["red_price"] if s else x["blue_price"]
        ev[x["e"]].append((price, (x["y"] == 1.0) == s))
    pnl, stk, n = [], [], 0
    for bets in ev.values():
        stake = min(10.0, 50.0 / len(bets))
        pnl.append(sum(stake * (p - 1) if w else -stake for p, w in bets))
        stk.append(stake * len(bets))
        n += len(bets)
    pnl, stk = np.array(pnl), np.array(stk)
    rng = np.random.default_rng(0)
    ix = rng.integers(0, len(pnl), (3000, len(pnl)))
    roi = pnl[ix].sum(axis=1) / stk[ix].sum(axis=1)
    mean_price = np.mean([p for b in ev.values() for p, _ in b])
    print(f"{name:50s} bets {n:5d}  staked {stk.sum():7.0f}  profit {pnl.sum():+8.1f}  ROI {pnl.sum()/stk.sum():+6.1%} [{np.percentile(roi,2.5):+.0%}, {np.percentile(roi,97.5):+.0%}]  mean price {mean_price:.2f}", flush=True)
    return pnl.sum() / stk.sum()


mv = lambda x: BETA * (lg(x["model"]) - lg(x["po"]))
fav_red = lambda x: x["po"] >= 0.5
run("all favourites at the open (no model)", lambda x: fav_red(x))
run("H3 rule (the C1 strategy)", lambda x: (mv(x) > 0) if abs(mv(x)) > 0.05 else None)
run("H3 rule, only bets on the open favourite", lambda x: (mv(x) > 0) if abs(mv(x)) > 0.05 and ((mv(x) > 0) == fav_red(x)) else None)
run("H3 rule, only bets on the open underdog", lambda x: (mv(x) > 0) if abs(mv(x)) > 0.05 and ((mv(x) > 0) != fav_red(x)) else None)
run("model's pick at the open, every fight", lambda x: x["model"] >= 0.5)
rule_roi = run("H3 rule again (for the shuffle below)", lambda x: (mv(x) > 0) if abs(mv(x)) > 0.05 else None)
rng = np.random.default_rng(1)
sel = [x for x in data if abs(mv(x)) > 0.05]
rois = []
for _ in range(200):
    flip = {id(x): rng.random() < 0.5 for x in sel}
    ev = defaultdict(list)
    for x in sel:
        s = flip[id(x)]
        ev[x["e"]].append(((x["red_price"] if s else x["blue_price"]), (x["y"] == 1.0) == s))
    pnl = stk = 0.0
    for bets in ev.values():
        stake = min(10.0, 50.0 / len(bets))
        pnl += sum(stake * (p - 1) if w else -stake for p, w in bets)
        stk += stake * len(bets)
    rois.append(pnl / stk)
print(f"random sides of the same fights, 200 shuffles: mean ROI {np.mean(rois):+.1%}, 5th to 95th percentile [{np.percentile(rois,5):+.1%}, {np.percentile(rois,95):+.1%}]; the rule beat {np.mean(np.array(rois) < rule_roi):.0%} of them")
