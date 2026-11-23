"""Flat 10-unit bet on every fight that has odds, under several simple rules. Uses stored walk-forward predictions."""
import duckdb
import numpy as np

c = duckdb.connect('data/processed/ufc.duckdb', read_only=True)
rows = c.execute("""
with w as (
  select bout_id,
         max(case when corner='red' then fighter_id end) red,
         max(case when corner='blue' then fighter_id end) blue,
         max(case when result='win' and corner='red' then 1 when result='win' and corner='blue' then 0 end) red_won
  from bout_fighter group by 1),
o as (select bout_id, fighter_id, min(price_decimal) price from odds_snapshots group by 1,2),
p as (select bout_id, model, p_red from predictions_ml)
select w.bout_id, e.date, w.red_won, ro.price, bo.price,
       max(case when p.model='stack' then p.p_red end) stack, max(case when p.model='B2_lr' then p.p_red end) lr
from w join bouts b using(bout_id) join events e on e.event_id=b.event_id
join o ro on ro.bout_id=w.bout_id and ro.fighter_id=w.red
join o bo on bo.bout_id=w.bout_id and bo.fighter_id=w.blue
join p on p.bout_id=w.bout_id
where w.red_won is not null
group by 1,2,3,4,5
""").fetchall()
rows = [r for r in rows if r[3] and r[4] and r[5] is not None and r[6] is not None]
print("bouts with odds, a prediction and a decisive result:", len(rows), "dates", min(r[1] for r in rows), max(r[1] for r in rows))
STAKE = 10.0


def run(name, choose):
    pnl, n, hit = 0.0, 0, 0
    for _, _, rw, ro, bo, ps, pl in rows:
        side = choose(ro, bo, ps, pl)
        if side is None:
            continue
        odds = ro if side == 1 else bo
        won = (rw == 1) if side == 1 else (rw == 0)
        pnl += STAKE * (odds - 1) if won else -STAKE
        n += 1
        hit += won
    print(f"{name:42s} bets {n:5d}  staked {n*STAKE:9,.0f}  profit {pnl:+10,.2f}  ROI {pnl/(n*STAKE):+.1%}  hit {hit/n:.1%}")


run("Bet on the model's pick (lr)", lambda ro, bo, ps, pl: 1 if pl >= .5 else 0)
run("Bet on the model's pick (stack)", lambda ro, bo, ps, pl: 1 if ps >= .5 else 0)
run("Bet on the market favourite", lambda ro, bo, ps, pl: 1 if ro < bo else 0)
run("Bet on the market underdog", lambda ro, bo, ps, pl: 1 if ro > bo else 0)
run("Bet on red corner", lambda ro, bo, ps, pl: 1)
ov = np.array([1 / r[3] + 1 / r[4] for r in rows])
print(f"implied-probability sum (1.00 = no bookmaker margin): mean {ov.mean():.3f}, median {np.median(ov):.3f}, share below 1.00: {(ov < 1).mean():.1%}")


def boot(choose, seed=0):
    pr = np.array([(STAKE * ((r[3] if choose(r) else r[4]) - 1) if ((r[2] == 1) == choose(r)) else -STAKE) for r in rows])
    rng = np.random.default_rng(seed)
    m = pr[rng.integers(0, len(pr), (4000, len(pr)))].mean(axis=1) / STAKE
    return pr, np.percentile(m, [2.5, 97.5])


pick = lambda r: r[6] >= .5
fav = lambda r: r[3] < r[4]
pp, ci = boot(pick)
pf, cf = boot(fav)
print(f"model pick ROI {pp.mean()/STAKE:+.1%}  95% CI [{ci[0]:+.1%}, {ci[1]:+.1%}]")
print(f"favourite  ROI {pf.mean()/STAKE:+.1%}  95% CI [{cf[0]:+.1%}, {cf[1]:+.1%}]")
d = pp - pf
rng = np.random.default_rng(1)
dm = d[rng.integers(0, len(d), (4000, len(d)))].mean(axis=1) / STAKE
print(f"model pick minus favourite ROI {d.mean()/STAKE:+.1%}  95% CI [{np.percentile(dm,2.5):+.1%}, {np.percentile(dm,97.5):+.1%}]; picks differ on {np.mean([pick(r)!=fav(r) for r in rows]):.1%} of fights")
for y in sorted({str(r[1])[:4] for r in rows}):
    rr = [r for r in rows if str(r[1])[:4] == y]
    pnl = sum((STAKE * ((r[3] if pick(r) else r[4]) - 1) if ((r[2] == 1) == pick(r)) else -STAKE) for r in rr)
    print(f"  {y}: {len(rr)} bets, profit {pnl:+,.0f}")
# both sides: loses the overround every time
pnl = 0.0
for _, _, rw, ro, bo, *_ in rows:
    pnl += (STAKE * (ro - 1) - STAKE) if rw == 1 else (STAKE * (bo - 1) - STAKE)
print(f"{'Both sides of every fight (10 each)':42s} bets {2*len(rows):5d}  staked {2*len(rows)*STAKE:9,.0f}  profit {pnl:+10,.2f}  ROI {pnl/(2*len(rows)*STAKE):+.1%}")
# model pick only when it agrees with favourite / disagrees
run("Model pick, only when it picks the underdog", lambda ro, bo, ps, pl: (1 if pl >= .5 else 0) if ((pl >= .5) == (ro > bo)) else None)
