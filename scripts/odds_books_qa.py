import duckdb
import numpy as np

c = duckdb.connect('data/processed/ufc.duckdb', read_only=True)
print(c.execute("select count(*), count(distinct bout_id), count(distinct bookmaker) from odds_books").fetchall())
print(c.execute("select bookmaker, count(distinct bout_id) n from odds_books group by 1 order by n desc").fetchall())
print(c.execute("""select min(e.date), max(e.date), count(distinct b.bout_id) from odds_books o join bouts b using(bout_id)
                   join events e using(event_id)""").fetchall())
print("bouts since 2023-06-01 in db:", c.execute("select count(*) from bouts b join events e using(event_id) where e.date>='2023-06-01'").fetchall())
# per-book overround
rows = c.execute("""select bout_id, bookmaker, 1/max(case when rn=1 then price_decimal end) + 1/max(case when rn=2 then price_decimal end) ov
  from (select *, row_number() over (partition by bout_id, bookmaker order by fighter_id) rn from odds_books) group by 1,2""").fetchall()
by = {}
for _, bk, ov in rows:
    by.setdefault(bk, []).append(ov)
for bk, v in sorted(by.items(), key=lambda x: -len(x[1])):
    v = np.array(v)
    print(f"{bk:12s} n={len(v):4d} median overround {np.median(v):.3f}  p10 {np.percentile(v,10):.3f}  p90 {np.percentile(v,90):.3f}")
# consensus (median of per-book de-vigged) per bout vs the old file where they overlap
old = {}
for b, f, p in c.execute("select bout_id, fighter_id, price_decimal from odds_snapshots").fetchall():
    old.setdefault(b, {})[f] = p
new = {}
for b, bk, f, p in c.execute("select bout_id, bookmaker, fighter_id, price_decimal from odds_books").fetchall():
    new.setdefault(b, {}).setdefault(bk, {})[f] = p
diffs, n = [], 0
for b, books in new.items():
    if b not in old or len(old[b]) != 2:
        continue
    fa, fb = sorted(old[b])
    po = (1 / old[b][fa]) / (1 / old[b][fa] + 1 / old[b][fb])
    ps = []
    for bk, d in books.items():
        if fa in d and fb in d:
            ps.append((1 / d[fa]) / (1 / d[fa] + 1 / d[fb]))
    if ps:
        diffs.append(np.median(ps) - po)
if diffs:
    d = np.array(diffs)
    print(f"overlap with old file: {len(d)} bouts, mean diff in win prob {d.mean():+.4f}, mean abs {np.abs(d).mean():.4f}, corr-check max {np.abs(d).max():.3f}")
else:
    print("no overlap with the old file")
