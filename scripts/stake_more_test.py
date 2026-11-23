"""Read-only: what happens if the staking rule deploys more of the 50? Same 102 cards with real sportsbook prices (2023-06 to 2025-10-18), same
probabilities (model blended with the market, the stack's own weight from earlier folds), best sportsbook price. Variants differ only in how much
of the budget the same value bets use:
  current           quarter Kelly, edge above 3%, halved for thin data and big gaps, cap 20% per fight   (what the page uses now)
  half Kelly / full Kelly   the same with Kelly fraction 0.5 and 1.0
  deploy all 50     the same bets (edge above 3%), scaled up so the card stakes the full 50, split in proportion to the Kelly amounts, cap 20%
  deploy all 50, edge above 0   the same with every positive-edge side
Intervals treat each card as one unit."""
import json
from collections import defaultdict
from statistics import median

import duckdb
import numpy as np

from ufcmodel.eval.betting_eval import MarketOfRecord

BANK, CAPF, EDGE = 50.0, 0.20, 0.03
con = duckdb.connect("data/processed/ufc.duckdb", read_only=True)
mk = MarketOfRecord()
W = {k: v[0] for k, v in json.load(open("data/processed/stack.json")).items()}
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
    pm, src = mk.close(b)
    if len(pr) < 3 or src != "books":
        continue
    w = W.get(ev[b][1][:4], 0.5)
    fights[ev[b][0]].append(dict(ps=float(sg(w * lg(pred[b]) + (1 - w) * lg(pm))), pm=pm, best=mk.best(b), red_won=win[b] == "red",
                                 thin=min(prior.get((b, mk.red[b]), 0), prior.get((b, mk.blue[b]), 0)) < 3))
events = [e for e, fs in fights.items() if len(fs) >= 4]


def bets(fs, kappa, edge, deploy):
    cand = []
    for f in fs:
        for red, p, pm, o in ((True, f["ps"], f["pm"], f["best"][0]), (False, 1 - f["ps"], 1 - f["pm"], f["best"][1])):
            e = p * o - 1
            if e > edge:
                m = (0.5 if f["thin"] else 1.0) * (0.5 if abs(p - pm) > 0.15 else 1.0)
                cand.append([kappa * e / (o - 1) * BANK * m, o, f["red_won"] == red])
    if not cand:
        return []
    if deploy:                      # rescale so the card stakes the full budget, respecting the per-fight cap (a few passes)
        raw = np.array([c[0] for c in cand]); stakes = raw / raw.sum() * BANK
        for _ in range(5):
            over = stakes > CAPF * BANK
            if not over.any() or (~over).sum() == 0:
                break
            stakes[over] = CAPF * BANK
            stakes[~over] = raw[~over] / raw[~over].sum() * (BANK - stakes[over].sum())
        stakes = np.minimum(stakes, CAPF * BANK)
        return [(s, c[1], c[2]) for s, c in zip(stakes, cand)]
    st = [min(CAPF * BANK, c[0]) for c in cand]
    s = min(1.0, BANK / sum(st))
    return [(x * s, c[1], c[2]) for x, c in zip(st, cand)]


rng = np.random.default_rng(0)
print(f"{len(events)} cards\n{'variant':34s} {'staked':>8s} {'per card':>8s} {'profit':>9s} {'ROI':>7s} {'ROI 95%':>14s} {'cards up':>9s} {'worst':>8s} {'best':>8s} {'sd/card':>8s}")
for name, kappa, edge, deploy in (("current (quarter Kelly)", 0.25, EDGE, False), ("half Kelly", 0.5, EDGE, False), ("full Kelly", 1.0, EDGE, False),
                                  ("deploy all 50, edge above 3%", 1.0, EDGE, True), ("deploy all 50, any positive edge", 1.0, 0.0, True)):
    pnl, stk = [], []
    for e in events:
        bs = bets(fights[e], kappa, edge, deploy)
        pnl.append(sum(s * (o - 1) if w else -s for s, o, w in bs)); stk.append(sum(s for s, _, _ in bs))
    pnl, stk = np.array(pnl), np.array(stk)
    ix = rng.integers(0, len(events), (4000, len(events)))
    roi = pnl[ix].sum(axis=1) / np.maximum(stk[ix].sum(axis=1), 1e-9)
    print(f"{name:34s} {stk.sum():8.0f} {stk.mean():8.2f} {pnl.sum():+9.1f} {pnl.sum() / stk.sum():+7.1%} [{np.percentile(roi, 2.5):+5.0%},{np.percentile(roi, 97.5):+5.0%}] {int((pnl > 0).sum()):>5d}/{int((stk > 0).sum()):<3d} {pnl.min():+8.1f} {pnl.max():+8.1f} {pnl.std():8.2f}")
