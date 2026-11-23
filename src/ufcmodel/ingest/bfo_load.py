"""Read the cached fighter pages into `odds_open_close`, matched to bouts. Lives in its own database file
(data/processed/odds_oc.duckdb) so a running crawl never blocks it; the main database is only read, and is ATTACHed read-only
by anything that needs both. One row per bout, in the bout's red/blue orientation.

A fight shows on both fighters' pages with the same prices, so the two copies are compared (QA) and the first is kept."""
import gzip
from datetime import timedelta

import duckdb

from ufcmodel.ingest.bfo import _lookup, norm
from ufcmodel.ingest.bfo_fighters import RAW, parse_fighter

OUT = "data/processed/odds_oc.duckdb"


def load(main_path="data/processed/ufc.duckdb", out_path=OUT):
    con = duckdb.connect(main_path, read_only=True)
    alias = _lookup(con)
    cand = {}   # frozenset pair -> [(bout_id, red, blue, date)]
    for b, r, u, d in con.execute("""SELECT b.bout_id, r.fighter_id, u.fighter_id, e.date FROM bouts b JOIN events e USING (event_id)
        JOIN bout_fighter r ON r.bout_id = b.bout_id AND r.corner = 'red' JOIN bout_fighter u ON u.bout_id = b.bout_id AND u.corner = 'blue'""").fetchall():
        cand.setdefault(frozenset((r, u)), []).append((b, r, u, d))
    con.close()
    got, diffs, pages, seen_rows, unmatched = {}, [], 0, 0, 0
    for f in sorted(RAW.glob("*.html.gz")):
        pages += 1
        for r in parse_fighter(gzip.decompress(f.read_bytes()).decode("utf-8")):
            seen_rows += 1
            fa, fb = alias.get(norm(r["fighter"] or "")), alias.get(norm(r["opponent"] or ""))
            if not (fa and fb and r["date"] and r["open_a"] and r["open_b"]):
                unmatched += 1
                continue
            hits = [c for c in cand.get(frozenset((fa, fb)), []) if abs((c[3] - r["date"]).days) <= 3]
            if not hits:
                unmatched += 1
                continue
            b, red, blue, d = min(hits, key=lambda c: abs((c[3] - r["date"]).days))
            sw = fa != red   # the page's fighter is the blue corner
            rec = dict(bout_id=b, red=red, blue=blue, date=d, mu=r["mu"],
                       open_red=r["open_b"] if sw else r["open_a"], open_blue=r["open_a"] if sw else r["open_b"],
                       low_red=r["low_b"] if sw else r["low_a"], high_red=r["high_b"] if sw else r["high_a"],
                       low_blue=r["low_a"] if sw else r["low_b"], high_blue=r["high_a"] if sw else r["high_b"])
            if b in got:
                diffs.append(abs(got[b]["open_red"] - rec["open_red"]))
            else:
                got[b] = rec
    out = duckdb.connect(out_path)
    out.execute("""CREATE OR REPLACE TABLE odds_open_close (bout_id VARCHAR, red VARCHAR, blue VARCHAR, date DATE, mu BIGINT,
        open_red DOUBLE, open_blue DOUBLE, low_red DOUBLE, high_red DOUBLE, low_blue DOUBLE, high_blue DOUBLE)""")
    cols = ["bout_id", "red", "blue", "date", "mu", "open_red", "open_blue", "low_red", "high_red", "low_blue", "high_blue"]
    out.executemany("INSERT INTO odds_open_close VALUES (?,?,?,?,?,?,?,?,?,?,?)", [[v[c] for c in cols] for v in got.values()])
    out.close()
    return dict(pages=pages, rows=seen_rows, bouts=len(got), unmatched=unmatched, both_copies=len(diffs),
                mean_abs_open_diff=(sum(diffs) / len(diffs) if diffs else None))


if __name__ == "__main__":
    print(load())
