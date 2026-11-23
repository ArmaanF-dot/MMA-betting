"""Stage 1 QA: coverage of open/close lines by year, and agreement with the per-book data (2023-06 on) and the old betmma file."""
from collections import defaultdict

import duckdb
import numpy as np

from ufcmodel.eval.betting_eval import MarketOfRecord, devig

con = duckdb.connect("data/processed/ufc.duckdb", read_only=True)
mk = MarketOfRecord()
bouts = con.execute("""SELECT b.bout_id, CAST(e.date AS VARCHAR) FROM bouts b JOIN events e USING (event_id)
                       WHERE b.method IS NOT NULL AND b.method NOT LIKE 'Overturned%'""").fetchall()
cov = defaultdict(lambda: [0, 0, 0])
for b, d in bouts:
    y = d[:4]
    cov[y][0] += 1
    cov[y][1] += b in mk.oc and mk.open(b) is not None
    cov[y][2] += mk.close(b)[0] is not None
print("year  bouts  with open+close  with any close price")
for y in sorted(cov):
    if y >= "2014":
        n, o, c = cov[y]
        print(f"{y}  {n:5d}  {o:5d} ({o/n:.0%})       {c:5d} ({c/n:.0%})")
tot = [sum(cov[y][i] for y in cov if "2015" <= y <= "2025") for i in range(3)]
print(f"2015-2025: {tot[0]} bouts, {tot[1]} with open+close ({tot[1]/tot[0]:.1%}), {tot[2]} with any close ({tot[2]/tot[0]:.1%})")
d_books, d_old, bias_b = [], [], []
for b, d in bouts:
    o = mk.oc.get(b)
    if not o or not all(o[k] for k in ("low_red", "high_red", "low_blue", "high_blue")):
        continue
    rng_p = devig((o["low_red"] + o["high_red"]) / 2, (o["low_blue"] + o["high_blue"]) / 2)
    pr = mk.book_prices(b)
    if len(pr) >= 3:
        pb = float(np.median([devig(a, c) for a, c in pr]))
        d_books.append(rng_p - pb)
    old = mk.old.get(b, {})
    if mk.red[b] in old and mk.blue[b] in old:
        d_old.append(rng_p - devig(old[mk.red[b]], old[mk.blue[b]]))
for name, v in (("per-book median (2023-06 on)", d_books), ("old betmma file", d_old)):
    v = np.array(v)
    print(f"closing-range midpoint vs {name}: n={len(v)}, mean diff {v.mean():+.4f}, mean abs {np.abs(v).mean():.4f}, 95th pct abs {np.percentile(np.abs(v), 95):.3f}")
