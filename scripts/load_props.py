"""Read prop prices (goes to decision, wins inside distance) from the cached Best Fight Odds pages into `odds_props`. No requests."""
import gzip
from datetime import date

from ufcmodel.db import connect
from ufcmodel.ingest import bfo

con = connect("data/processed/ufc.duckdb")
con.execute("""CREATE OR REPLACE TABLE odds_props (bout_id VARCHAR, bookmaker VARCHAR, market VARCHAR, fighter_id VARCHAR,
               yes_price DOUBLE, no_price DOUBLE)""")
alias = bfo._lookup(con)
tot = {"distance": 0, "inside": 0}
for d, url in bfo.event_urls(date(2023, 6, 1), date(2026, 10, 26)):
    f = bfo.RAW / f"{url.rsplit('/', 1)[-1][-28:]}.html.gz"
    if not f.exists():
        continue
    fights = bfo.parse_props(gzip.decompress(f.read_bytes()).decode("utf-8"))
    matched, missed, _ = bfo.match_event(con, alias, d, fights)
    rows = []
    for bout, fa, fb, props in matched:
        for mk, per in props.items():
            fid = {"distance": None, "inside_a": fa, "inside_b": fb}[mk]
            for bk, (y, n) in per.items():
                rows.append((bout, bk, "distance" if mk == "distance" else "inside", fid, y, n))
                tot["distance" if mk == "distance" else "inside"] += 1
    if rows:
        con.executemany("INSERT INTO odds_props VALUES (?, ?, ?, ?, ?, ?)", rows)
print(tot, con.execute("select market, count(distinct bout_id), count(*) from odds_props group by 1").fetchall())
print(con.execute("select market, bookmaker, count(*) from odds_props group by 1,2 order by 3 desc limit 8").fetchall())
