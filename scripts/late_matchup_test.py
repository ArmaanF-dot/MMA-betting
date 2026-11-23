"""Late-created matchups: the site's matchup id grows with the time a matchup was made. A fight whose id is more than 150 above the median
id of its own event (about 2 to 3 weeks later than a typical card fight, at roughly 8 to 10 ids a day) is flagged 'late'. The
threshold is fixed here before looking; the id-gap quantiles are printed only as a sanity check.
Test: do late fights go differently from what the market expected? The favourite's win rate against the market's probability, the
share going the distance against the market's, and how often the favourite's price drifted (open to close).
Prices: the market of record (close); bouts with a close price only."""
from collections import defaultdict

import duckdb
import numpy as np

from ufcmodel.eval.betting_eval import MarketOfRecord, flat_returns

THRESH = 150
con = duckdb.connect("data/processed/ufc.duckdb", read_only=True)
oc = duckdb.connect("data/processed/odds_oc.duckdb", read_only=True)
mu = {b: m for b, m in oc.execute("SELECT bout_id, mu FROM odds_open_close WHERE mu IS NOT NULL").fetchall()}
ev = {b: (e, str(d)) for b, e, d in con.execute("SELECT b.bout_id, b.event_id, e.date FROM bouts b JOIN events e USING (event_id)").fetchall()}
win = {b: c for b, c in con.execute("SELECT bout_id, corner FROM bout_fighter WHERE result = 'win'").fetchall()}
meth = dict(con.execute("SELECT bout_id, method FROM bouts").fetchall())
by_event = defaultdict(list)
for b, m in mu.items():
    if b in ev:
        by_event[ev[b][0]].append(m)
med = {e: float(np.median(v)) for e, v in by_event.items() if len(v) >= 5}
gaps = np.array([mu[b] - med[ev[b][0]] for b in mu if b in ev and ev[b][0] in med])
print(f"bouts with an id and an event of 5+ ids: {len(gaps)}; gap quantiles 50/75/90/95/99: {np.percentile(gaps, [50, 75, 90, 95, 99]).round(0)}; share above {THRESH}: {(gaps > THRESH).mean():.1%}")
mk = MarketOfRecord()
rows = []
for b in mu:
    if b not in ev or ev[b][0] not in med or b not in win:
        continue
    p, src = mk.close(b)
    if p is None:
        continue
    fav_red = p >= 0.5
    pf = max(p, 1 - p)
    op = mk.open(b)
    drift = None if op is None else (max(op, 1 - op) if fav_red == (op >= 0.5) else 1 - max(op, 1 - op))
    rows.append(dict(late=mu[b] - med[ev[b][0]] > THRESH, fav_won=(win[b] == "red") == fav_red, pf=pf, dec=meth[b] == "Decision",
                     event=ev[b][0], yr=ev[b][1][:4], drift=None if drift is None else pf - drift))
for label, sel in (("late", [r for r in rows if r["late"]]), ("not late", [r for r in rows if not r["late"]])):
    fw = np.mean([r["fav_won"] for r in sel])
    ep = np.mean([r["pf"] for r in sel])
    dr = [r["drift"] for r in sel if r["drift"] is not None]
    print(f"{label:9s} n={len(sel):5d}  favourite won {fw:.1%} vs market {ep:.1%}  (gap {fw-ep:+.1%});  goes to decision {np.mean([r['dec'] for r in sel]):.1%};  mean favourite move open->close {np.mean(dr):+.3f}")
late = [r for r in rows if r["late"]]
res = np.array([float(r["fav_won"]) - r["pf"] for r in late])
rng = np.random.default_rng(0)
g = defaultdict(list)
for r, x in zip(late, res):
    g[r["event"]].append(x)
ev_means = [(sum(v), len(v)) for v in g.values()]
idx = rng.integers(0, len(ev_means), (4000, len(ev_means)))
s = np.array([a for a, _ in ev_means])
c = np.array([b for _, b in ev_means])
boot = s[idx].sum(axis=1) / c[idx].sum(axis=1)
print(f"late fights, favourite result minus market probability: {res.mean():+.3f}  95% [{np.percentile(boot, 2.5):+.3f}, {np.percentile(boot, 97.5):+.3f}]  ({len(late)} fights, {len(g)} events)")


def resid(sel):
    """Favourite result minus market probability, with a 95% interval from a bootstrap over events."""
    gg = defaultdict(list)
    for r in sel:
        gg[r["event"]].append(float(r["fav_won"]) - r["pf"])
    sums = np.array([sum(v) for v in gg.values()])
    cnts = np.array([len(v) for v in gg.values()])
    ix = rng.integers(0, len(gg), (4000, len(gg)))
    bt = sums[ix].sum(axis=1) / cnts[ix].sum(axis=1)
    return sums.sum() / cnts.sum(), np.percentile(bt, 2.5), np.percentile(bt, 97.5), len(sel), len(gg)


print()
for period, lo, hi in (("discovery 2015-2021", "2015", "2021"), ("validation 2022-2025", "2022", "2025")):
    for label, flag in (("late", True), ("not late", False)):
        m, a, b, n, ne = resid([r for r in rows if r["late"] == flag and lo <= r["yr"] <= hi])
        print(f"{period:22s} {label:9s} favourite result minus market probability {m:+.3f} [{a:+.3f}, {b:+.3f}]  ({n} fights, {ne} events)")
