import gzip
from collections import Counter, defaultdict

from ufcmodel.ingest.bfo import _lookup, norm
from ufcmodel.ingest.bfo_fighters import RAW, parse_fighter
import duckdb

con = duckdb.connect("data/processed/ufc.duckdb", read_only=True)
alias = _lookup(con)
rows = defaultdict(list)
n = Counter()
for f in sorted(RAW.glob("*.html.gz")):
    for r in parse_fighter(gzip.decompress(f.read_bytes()).decode("utf-8")):
        n["rows"] += 1
        n["date"] += r["date"] is not None
        n["mu"] += r["mu"] is not None
        n["mu_with_date"] += (r["mu"] is not None and r["date"] is not None)
        fa = alias.get(norm(r["fighter"] or ""))
        if fa and r["date"]:
            rows[(fa, r["date"])].append((r["opponent"], r["mu"], r["event"]))
print(dict(n))
multi = {k: v for k, v in rows.items() if len({o for o, _, _ in v}) >= 2}
print("fighter-dates with 2+ different opponents:", len(multi), "of", len(rows))
print("of those, all rows have mu:", sum(all(m is not None for _, m, _ in v) for v in multi.values()))
for k, v in list(multi.items())[:6]:
    print(k[1], v)
