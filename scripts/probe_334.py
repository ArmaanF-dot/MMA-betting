import time

import httpx
from bs4 import BeautifulSoup

from ufcmodel.ingest.bfo import BASE, HEADERS, parse_event

for slug in ("ufc-334-4433", "ufc-334-4370"):
    r = httpx.get(f"{BASE}/events/{slug}", headers=HEADERS, timeout=60, follow_redirects=True)
    fights = parse_event(r.text)
    t = BeautifulSoup(r.text, "lxml").title
    print(f"\n{slug}: status {r.status_code}, title {t.string if t else None}")
    print(f"  {len(fights)} fights, {sum(1 for f in fights if f[2])} with sportsbook prices")
    for na, nb, per in fights[:14]:
        print(f"  {na} vs {nb}: {len(per)} books")
    time.sleep(4)
