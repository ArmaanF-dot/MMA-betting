"""The opening-line rule (C1, beta 0.1698 from discovery, threshold 0.05 logit) re-priced along each fight's price history.
Each fighter page carries a 10-point price series per fight (index 0 is the open, index 9 the close); the spacing in time is not
documented, so 'index 4 or 5' is only roughly 'mid-week'. A series is for the page's own fighter; the other side is rebuilt by
holding the opening margin fixed (the two implied probabilities sum to the opening overround). At each index the rule is applied
as a bettor would see it at that moment: selection from that index's fair probability, price from that index. Flat 10 per bet, so
the return does not depend on how many fights are covered. Validation years 2022 to 2025-10-24, the same bouts at every index."""
import gzip
import pickle
from collections import defaultdict
from datetime import timedelta

import duckdb
import numpy as np

from ufcmodel.eval.betting_eval import MarketOfRecord
from ufcmodel.ingest.bfo import _lookup, norm
from ufcmodel.ingest.bfo_fighters import RAW, parse_fighter

BETA = 0.1698
lg = lambda p: np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))
S = pickle.load(open("data/processed/stage3.pkl", "rb"))
con = duckdb.connect("data/processed/ufc.duckdb", read_only=True)
alias = _lookup(con)
mk = MarketOfRecord()
cand = defaultdict(list)
for b, r, u, d in con.execute("""SELECT b.bout_id, r.fighter_id, u.fighter_id, e.date FROM bouts b JOIN events e USING (event_id)
    JOIN bout_fighter r ON r.bout_id = b.bout_id AND r.corner = 'red' JOIN bout_fighter u ON u.bout_id = b.bout_id AND u.corner = 'blue'""").fetchall():
    cand[frozenset((r, u))].append((b, d))
series = {}      # (bout, fighter) -> 10 prices, from that fighter's own page
n_rows = n_ok = 0
s0_err = []
for f in sorted(RAW.glob("*.html.gz")):
    for r in parse_fighter(gzip.decompress(f.read_bytes()).decode("utf-8")):
        if not r["sparkline"] or not r["date"]:
            continue
        pts = [float(x) for x in r["sparkline"].split(",")]
        fa, fb = alias.get(norm(r["fighter"] or "")), alias.get(norm(r["opponent"] or ""))
        if len(pts) != 10 or not (fa and fb):
            continue
        hits = [c for c in cand.get(frozenset((fa, fb)), []) if abs((c[1] - r["date"]).days) <= 3]
        if not hits:
            continue
        b = min(hits, key=lambda c: abs((c[1] - r["date"]).days))[0]
        n_rows += 1
        if r["open_a"]:
            s0_err.append(abs(pts[0] - r["open_a"]))
        series[(b, fa)] = pts
print(f"{n_rows} series matched to bouts; |index 0 - the page's opening price|: median {np.median(s0_err):.4f}, 95th percentile {np.percentile(s0_err, 95):.4f}", flush=True)

rows = []
for x in S["data"]:
    if x["d"] < "2022-01-01" or not x["red_price"] or not x["blue_price"]:
        continue
    r_id, u_id = mk.red[x["b"]], mk.blue[x["b"]]
    key = (x["b"], r_id) if (x["b"], r_id) in series else ((x["b"], u_id) if (x["b"], u_id) in series else None)
    if key is None:
        continue
    pts = np.array(series[key])
    ov = 1 / x["red_price"] + 1 / x["blue_price"]
    ia = 1 / pts                                                   # the series fighter's implied probability, with margin
    ib = ov - ia                                                   # the other side, holding the opening margin fixed
    if np.any(ib <= 0.02) or np.any(ia <= 0.02):
        continue
    ired, iblue = (ia, ib) if key[1] == r_id else (ib, ia)
    rows.append(dict(e=x["e"], y=x["y"], model=x["model"], pr=1 / ired, pb=1 / iblue, fair_red=ired / (ired + iblue)))
print(f"{len(rows)} fights with a usable series in 2022-2025 (of {sum(1 for x in S['data'] if x['d'] >= '2022-01-01')}).", flush=True)
# faithfulness of the rebuild at the open
chk = [(abs(r["pr"][0] - x["red_price"]) + abs(r["pb"][0] - x["blue_price"])) for r, x in zip(rows, [x for x in S["data"] if x["d"] >= "2022-01-01" and x["red_price"] and x["blue_price"] and ((x["b"], mk.red[x["b"]]) in series or (x["b"], mk.blue[x["b"]]) in series)])]
print(f"rebuilt open vs actual open prices, mean absolute difference {np.mean(chk):.4f} (should be 0 for the series' own side and small for the rebuilt side)\n", flush=True)

print(f"{'index':>5s} {'bets':>5s} {'ROI':>7s} {'95% (events)':>16s} {'mean price':>10s} {'share on open underdog':>23s}")
for k in range(10):
    ev = defaultdict(list)
    n_dog, n = 0, 0
    for r in rows:
        mv = BETA * (lg(r["model"]) - lg(r["fair_red"][k]))
        if abs(mv) <= 0.05:
            continue
        red = mv > 0
        price = r["pr"][k] if red else r["pb"][k]
        ev[r["e"]].append(10 * (price - 1) if (r["y"] == 1.0) == red else -10.0)
        n += 1
        n_dog += price > 2.0
    allp = np.array([p for v in ev.values() for p in v])
    ev_sum = np.array([sum(v) for v in ev.values()])
    ev_n = np.array([len(v) for v in ev.values()])
    rng = np.random.default_rng(0)
    ix = rng.integers(0, len(ev_sum), (3000, len(ev_sum)))
    roi = ev_sum[ix].sum(axis=1) / ev_n[ix].sum(axis=1) / 10
    print(f"{k:5d} {n:5d} {allp.mean()/10:+7.1%} [{np.percentile(roi,2.5):+6.1%}, {np.percentile(roi,97.5):+6.1%}] {np.mean([1]) and '':>10s} {n_dog/n:>22.0%}", flush=True)
