import duckdb

c = duckdb.connect('data/processed/ufc.duckdb', read_only=True)
for t in ('fighters', 'fighter_aliases'):
    print(t, [r[0] for r in c.execute(f'describe {t}').fetchall()])
    print(c.execute(f'select * from {t} limit 2').fetchall())
print(c.execute("select kind, count(*) from odds_snapshots group by 1").fetchall())
print(c.execute("select max(e.date) from odds_snapshots o join bouts b using(bout_id) join events e using(event_id)").fetchall())
ev = open('data/raw/bfo/sitemap_events.txt').read().split()
print(len(ev))
