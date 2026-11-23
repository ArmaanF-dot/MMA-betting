"""GBP 10 flat on value bets only: bet a side when model_p * price - 1 > threshold. The threshold for each year is chosen using
earlier years only. Run with the file's own prices, and again with prices cut so the typical overround is about 5%."""
import duckdb
import numpy as np

STAKE = 10.0
THRS = (0.0, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20)
c = duckdb.connect('data/processed/ufc.duckdb', read_only=True)
rows = c.execute("""
with w as (
  select bout_id,
         max(case when corner='red' then fighter_id end) red,
         max(case when corner='blue' then fighter_id end) blue,
         max(case when result='win' and corner='red' then 1 when result='win' and corner='blue' then 0 end) red_won
  from bout_fighter group by 1),
o as (select bout_id, fighter_id, min(price_decimal) price from odds_snapshots group by 1,2)
select w.bout_id, extract(year from e.date), w.red_won, ro.price, bo.price,
       max(case when p.model='stack' then p.p_red end), max(case when p.model='B2_lr' then p.p_red end)
from w join bouts b using(bout_id) join events e on e.event_id=b.event_id
join o ro on ro.bout_id=w.bout_id and ro.fighter_id=w.red
join o bo on bo.bout_id=w.bout_id and bo.fighter_id=w.blue
join predictions_ml p on p.bout_id=w.bout_id
where w.red_won is not null group by 1,2,3,4,5""").fetchall()
rows = [r for r in rows if r[3] and r[4] and r[5] is not None and r[6] is not None and 1 < r[3] < 50 and 1 < r[4] < 50]
print("fights:", len(rows))


def bets(rs, k, thr, cut):
    out = []
    for _, y, rw, ro, bo, ps, pl in rs:
        p = (ps, pl)[k]
        ro, bo = ro / cut, bo / cut
        er, eb = p * ro - 1, (1 - p) * bo - 1
        if max(er, eb) > thr:
            red = er >= eb
            won = (rw == 1) if red else (rw == 0)
            out.append((y, STAKE * ((ro if red else bo) - 1) if won else -STAKE, won))
    return out


def walk(k, cut):
    allb = []
    for y in sorted({r[1] for r in rows})[1:]:
        prior = [r for r in rows if r[1] < y]
        best, bt = -9, 0.05
        for t in THRS:
            b = bets(prior, k, t, cut)
            if len(b) >= 100:
                roi = sum(x[1] for x in b) / (STAKE * len(b))
                if roi > best:
                    best, bt = roi, t
        allb += bets([r for r in rows if r[1] == y], k, bt, cut)
    return allb


rng = np.random.default_rng(0)
for cut, label in ((1.0, "file's own prices"), (1.044, "prices cut to a typical ~5% margin")):
    print(f"\n== {label} ==")
    for k, nm in ((0, "stack model"), (1, "logistic model")):
        b = walk(k, cut)
        pr = np.array([x[1] for x in b])
        m = pr[rng.integers(0, len(pr), (4000, len(pr)))].mean(axis=1) / STAKE
        print(f"{nm:15s} bets {len(b):4d}  staked {len(b)*STAKE:7,.0f}  profit {pr.sum():+9,.2f}  ROI {pr.mean()/STAKE:+.1%} [{np.percentile(m,2.5):+.1%}, {np.percentile(m,97.5):+.1%}]  hit {np.mean([x[2] for x in b]):.1%}")
        byy = {}
        for y, p_, _ in b:
            byy.setdefault(int(y), []).append(p_)
        print("   by year:", ", ".join(f"{y}: {len(v)} bets {sum(v):+,.0f}" for y, v in sorted(byy.items())))
