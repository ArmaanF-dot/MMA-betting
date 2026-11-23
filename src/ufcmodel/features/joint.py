"""Improvement 3: joint opponent adjustment.

For each stat, y_ij ~ Poisson(minutes_ij * exp(alpha + o_i - d_j)): every fighter's offence o and defence d are estimated
together (alternating closed-form updates with a gamma-style prior worth P_MIN minutes at the global rate, i.e. shrinkage to
average), recency-weighted with a 24-month half-life over an 8-year window. Refit at the start of every month on fights strictly
before that month, so a bout's features never see its own month. This replaces the one-pass chain used by the rate features,
where an opponent's factor came from their own, only partly adjusted, rates.
"""
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

STATS = ("sig_l", "td_l", "ctrl_sec")
HALF_LIFE_MONTHS = 24
WINDOW_YEARS = 8
P_MIN = 15.0
ITERS = 10
MIN_OBS = 300


def _fit(att, dfn, y, m, w, nf):
    tot = (w * y).sum()
    alpha = np.log(max(tot, 1e-9) / (w * m).sum())
    o, d = np.zeros(nf), np.zeros(nf)
    for _ in range(ITERS):
        ea = np.exp(alpha)
        o = np.log((np.bincount(att, w * y, nf) + P_MIN * ea) /
                   (np.bincount(att, w * m * np.exp(alpha - d[dfn]), nf) + P_MIN * ea))
        d = -np.log((np.bincount(dfn, w * y, nf) + P_MIN * ea) /
                    (np.bincount(dfn, w * m * np.exp(alpha + o[att]), nf) + P_MIN * ea))
        alpha = np.log(max(tot, 1e-9) / (w * m * np.exp(o[att] - d[dfn])).sum())
    return o, d


def add_joint_features(rows, raw_ordered, stats=STATS):
    ids = {}
    idx = lambda f: ids.setdefault(f, len(ids))
    obs = {s: ([], [], [], [], []) for s in stats}   # date, attacker, defender, y, minutes
    for b in raw_ordered:
        if b.score_a is None or not b.fight_sec:
            continue
        m = b.fight_sec / 60
        for s in stats:
            for att, dfn, st in ((b.a, b.b, b.stats_a), (b.b, b.a, b.stats_b)):
                if st.get(s) is not None:
                    col = obs[s]
                    col[0].append(b.date)
                    col[1].append(idx(att))
                    col[2].append(idx(dfn))
                    col[3].append(float(st[s]))
                    col[4].append(m)
    for r in rows:
        idx(r["a"])
        idx(r["b"])
    nf = len(ids)
    arr = {s: tuple(np.array(c) for c in obs[s]) for s in stats}
    by_month = defaultdict(list)
    for r in rows:
        by_month[r["date"][:7]].append(r)
    for month, mrows in sorted(by_month.items()):
        start = date.fromisoformat(month + "-01")
        lo = (start - timedelta(days=int(365.25 * WINDOW_YEARS))).isoformat()
        hi = start.isoformat()
        fits = {}
        for s in stats:
            dts, att, dfn, y, m = arr[s]
            if len(dts) == 0:
                continue
            sel = (dts < hi) & (dts >= lo)
            if sel.sum() < MIN_OBS:
                continue
            age_m = np.array([(start - date.fromisoformat(x)).days for x in dts[sel]]) / 30.44
            w = 0.5 ** (age_m / HALF_LIFE_MONTHS)
            fits[s] = _fit(att[sel], dfn[sel], y[sel], m[sel], w, nf)
        for r in mrows:
            ia, ib = ids[r["a"]], ids[r["b"]]
            for s in stats:
                if s in fits:
                    o, d = fits[s]
                    r[f"j_{s}_off"] = float(o[ia] - o[ib])
                    r[f"j_{s}_def"] = float(d[ia] - d[ib])
