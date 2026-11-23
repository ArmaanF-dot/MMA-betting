"""Phase 8 judging model, fitted from round stats and decision results.

UFCStats gives only each decision's final scorecard totals, not per-round scores, so a per-round logistic with judge random
effects cannot be fit directly. Instead: a logistic on the SUMMED per-round stat differences predicts who won each decision
(`w`), and a temperature `kappa` is then chosen so that three independent judges, each scoring every round
Bernoulli(sigmoid(kappa * w.x_round)), reproduce the observed decision-winner probabilities. 10-8 rounds and judge-specific
tendencies are not modelled (no per-round or judge-level labels), and that gap is logged in docs/decisions.md.
"""
from collections import defaultdict
from itertools import product

import numpy as np
from sklearn.linear_model import LogisticRegression

FEATS = ("sig/10", "kd", "td", "ctrl/60", "sub")
KAPPAS = (0.25, 0.5, 1.0, 1.5, 2.5, 4.0)


def round_vector(sig, kd, td, ctrl, sub):
    return np.array([sig / 10.0, kd, td, ctrl / 60.0, sub], float)


def load_decisions(con):
    """[(bout_id, date, y_A, X rounds x 5)] for decisions with a winner; A is the red corner."""
    q = """SELECT b.bout_id, CAST(e.date AS VARCHAR), r.fighter_id, u.fighter_id, r.result
           FROM bouts b JOIN events e USING (event_id)
           JOIN bout_fighter r ON r.bout_id = b.bout_id AND r.corner = 'red'
           JOIN bout_fighter u ON u.bout_id = b.bout_id AND u.corner = 'blue'
           WHERE b.method = 'Decision' AND r.result IN ('win', 'loss')"""
    meta = {bid: (d, a, b, res) for bid, d, a, b, res in con.execute(q).fetchall()}
    rows = defaultdict(dict)
    for bid, fid, n, sig, kd, td, ctrl, sub in con.execute(
            "SELECT bout_id, fighter_id, round, sig_l, kd, td_l, ctrl_sec, sub_att FROM rounds").fetchall():
        if bid in meta and None not in (sig, kd, td, sub):
            rows[bid].setdefault(n, {})[fid] = (sig, kd, td, ctrl or 0, sub)
    out = []
    for bid, rd in rows.items():
        d, a, b, res = meta[bid]
        xs = []
        for n in sorted(rd):
            if a in rd[n] and b in rd[n]:
                xs.append(round_vector(*rd[n][a]) - round_vector(*rd[n][b]))
        if len(xs) >= 3:
            out.append((bid, d, 1.0 if res == "win" else 0.0, np.array(xs)))
    return out


def p_decision_a(w, kappa, X):
    """P(A takes the decision) from the three judges' majority, for one fight with rounds X (R x 5). Exact by DP."""
    p = 1 / (1 + np.exp(-kappa * (X @ w)))
    dist = np.array([1.0])
    for pr in p:                       # distribution of rounds won by A for one judge
        dist = np.convolve(dist, [1 - pr, pr])
    R = len(p)
    a = dist[np.arange(R + 1) * 2 > R].sum()     # judge scores A the winner
    b = dist[np.arange(R + 1) * 2 < R].sum()
    t = 1 - a - b
    # three iid judges, each scoring A, B or a tie: A wins with at least two A votes and more A than B votes
    pa = pb = 0.0
    for v in product((1, -1, 0), repeat=3):
        pr = np.prod([a if x == 1 else b if x == -1 else t for x in v])
        na, nb = v.count(1), v.count(-1)
        if na >= 2 and na > nb:
            pa += pr
        elif nb >= 2 and nb > na:
            pb += pr
    return pa / (pa + pb) if pa + pb > 0 else 0.5


def fit_judging(decisions, before_date):
    train = [x for x in decisions if x[1] < before_date]
    if len(train) < 200:
        return np.array([0.6, 1.0, 0.8, 0.5, 0.3]), 1.0, len(train)
    X = np.array([x[3].sum(axis=0) for x in train])
    y = np.array([x[2] for x in train])
    lr = LogisticRegression(C=1.0, fit_intercept=False, max_iter=2000).fit(np.vstack([X, -X]), np.concatenate([y, 1 - y]))
    w = lr.coef_[0]
    best, best_ll = 1.0, np.inf
    for k in KAPPAS:
        ps = np.array([p_decision_a(w, k, x[3]) for x in train])
        ps = np.clip(ps, 1e-4, 1 - 1e-4)
        ll = -np.mean(y * np.log(ps) + (1 - y) * np.log(1 - ps))
        if ll < best_ll:
            best, best_ll = k, ll
    return w, best, len(train)
