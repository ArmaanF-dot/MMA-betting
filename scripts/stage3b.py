"""Stage 3 follow-up: checks that H3 and H4 are not artifacts, and the pre-registered H4 strategy.
 A. H3 robustness. delta = logit(close) - logit(open) can correlate with logit(model) - logit(open) for a worthless model: a noisy
    open drifts back to the truth. So: (i) free the open's coefficient, delta = a logit(model) + c logit(open) (a is the model's own
    information, c the drift back); (ii) placebos in the same formula: a constant 50% 'model', the Elo probability, and the model
    shuffled across bouts.
 B. H4 strategy (rule fixed in the plan): bet a side when p_H4 x best sportsbook price - 1 exceeds 3%, flat 10, validation fights with
    per-book prices (2023-06 on); also at the median price, and the same rule with the market's own probability in place of p_H4
    (that is line shopping alone, the bar H4 has to clear)."""
import pickle
from collections import defaultdict
from statistics import median

import numpy as np

from ufcmodel.eval.betting_eval import MarketOfRecord, clv, flat_returns

S = pickle.load(open("data/processed/stage3.pkl", "rb"))
data, b11, mean, sd = S["data"], S["b11"], S["mean11"], S["sd11"]
lg = lambda p: np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))
out = ["# Stage 3 follow-up: robustness of H3 and the H4 strategy", ""]


def say(s=""):
    print(s, flush=True)
    out.append(s)


def ols(X, y, groups):
    X, y = np.asarray(X, float), np.asarray(y, float)
    inv = np.linalg.inv(X.T @ X)
    beta = inv @ X.T @ y
    res = y - X @ beta
    meat = np.zeros((X.shape[1],) * 2)
    idx = defaultdict(list)
    for k, g in enumerate(groups):
        idx[g].append(k)
    for ks in idx.values():
        s = X[ks].T @ res[ks]
        meat += np.outer(s, s)
    return beta, np.sqrt(np.diag(inv @ meat @ inv))


say("## A. H3 robustness")
say("")
say("| Period | Check | Coefficient [95%] |")
say("|---|---|---|")
rng = np.random.default_rng(0)
for label, lo, hi in (("2015-2021", "0", "2022"), ("2022-2025", "2022", "9")):
    rs = [x for x in data if lo <= x["d"] < hi and x["po"] is not None and x["pc_oc"] is not None]
    d = np.array([lg(x["pc_oc"]) - lg(x["po"]) for x in rs])
    g = [x["e"] for x in rs]
    lo_ = np.array([lg(x["po"]) for x in rs])
    lm = np.array([lg(x["model"]) for x in rs])
    le = np.array([lg(x["elo"]) for x in rs])
    b, s = ols((lm - lo_)[:, None], d, g)
    say(f"| {label} | model, the pre-set formula (x = model - open) | {b[0]:+.4f} [{b[0]-1.96*s[0]:+.4f}, {b[0]+1.96*s[0]:+.4f}] |")
    b, s = ols(np.column_stack([lm, lo_]), d, g)
    say(f"| {label} | free open: coefficient on logit(model) | {b[0]:+.4f} [{b[0]-1.96*s[0]:+.4f}, {b[0]+1.96*s[0]:+.4f}] |")
    say(f"| {label} | free open: coefficient on logit(open) (drift back) | {b[1]:+.4f} [{b[1]-1.96*s[1]:+.4f}, {b[1]+1.96*s[1]:+.4f}] |")
    b, s = ols((-lo_)[:, None], d, g)
    say(f"| {label} | placebo: constant 50% model (x = -logit(open)) | {b[0]:+.4f} [{b[0]-1.96*s[0]:+.4f}, {b[0]+1.96*s[0]:+.4f}] |")
    b, s = ols((le - lo_)[:, None], d, g)
    say(f"| {label} | placebo: Elo probability | {b[0]:+.4f} [{b[0]-1.96*s[0]:+.4f}, {b[0]+1.96*s[0]:+.4f}] |")
    perm = rng.permutation(lm)
    b, s = ols((perm - lo_)[:, None], d, g)
    say(f"| {label} | placebo: model shuffled across bouts | {b[0]:+.4f} [{b[0]-1.96*s[0]:+.4f}, {b[0]+1.96*s[0]:+.4f}] |")
say("")

say("## B. H4 strategy on validation fights with per-book prices")
say("")
mk = MarketOfRecord()
val = [x for x in data if x["d"] >= "2022-01-01" and len(mk.book_prices(x["b"])) >= 3]
F = np.array([x["f"] for x in val], float)
z = np.array([lg(x["pc"]) for x in val]) + ((F - mean) / sd) @ b11
p_h4 = 1 / (1 + np.exp(-z))
say(f"{len(val)} fights. Mean |p_H4 - market| = {np.mean(np.abs(p_h4 - np.array([x['pc'] for x in val]))):.4f}; fights where p_H4 differs from the market by more than 2 points: {np.mean(np.abs(p_h4 - np.array([x['pc'] for x in val])) > 0.02):.0%}.")
say("")
say("| Probability used | Price | Bets | Profit | Return [95%, events as units] | Mean closing-line value |")
say("|---|---|---|---|---|---|")
for pname, pv in (("H4", p_h4), ("market only (line shopping)", np.array([x["pc"] for x in val]))):
    for price in ("best", "median"):
        prof, evs, cl = [], [], []
        for x, p in zip(val, pv):
            bp = mk.best(x["b"]) if price == "best" else (median(a for a, _ in mk.book_prices(x["b"])), median(c for _, c in mk.book_prices(x["b"])))
            er, eb = p * bp[0] - 1, (1 - p) * bp[1] - 1
            if max(er, eb) <= 0.03:
                continue
            red = er >= eb
            won = (x["y"] == 1.0) == red
            prof.append(10 * (bp[0 if red else 1] - 1) if won else -10.0)
            evs.append(x["e"])
            cl.append(clv(bp[0 if red else 1], x["pc"] if red else 1 - x["pc"]))
        r = flat_returns(prof, evs, stake=10.0)
        if r["n"]:
            say(f"| {pname} | {price} | {r['n']} | {r['profit']:+,.0f} | {r['roi']:+.1%} [{r['lo']:+.1%}, {r['hi']:+.1%}] | {np.mean(cl):+.4f} |")
        else:
            say(f"| {pname} | {price} | 0 | | | |")
say("")
open("docs/stage3b_results.md", "w", encoding="utf-8").write("\n".join(out))
print("ALLDONE", flush=True)
