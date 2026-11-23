import httpx

from ufcmodel.ingest.bfo import HEADERS
from ufcmodel.ingest.bfo_fighters import parse_fighter

for u in ("https://www.bestfightodds.com/fighters/bethe-correia-4553", "https://www.bestfightodds.com/fighters/donald-cerrone-1148"):
    r = httpx.get(u, headers=HEADERS, timeout=60)
    rows = parse_fighter(r.text)
    ds = sorted(x["date"] for x in rows if x["date"])
    print(u, r.status_code, len(rows), "fights", ds[0] if ds else None, "to", ds[-1] if ds else None, "with open:", sum(1 for x in rows if x["open_a"]))
