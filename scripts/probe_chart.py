import json
import re
import time
from datetime import datetime, timezone

import httpx

from ufcmodel.ingest.bfo import BASE, HEADERS

for m, p in ((44524, 1), (37752, 1), (45459, 1)):          # UFC 333 main event, a late 2025 fight, a Vegas 123 fight
    r = httpx.get(f"{BASE}/api/ggd", params={"m": m, "p": p}, headers=HEADERS, timeout=60)
    print(m, p, r.status_code, len(r.text), r.headers.get("content-type"))
    print(r.text[:400].replace("\n", " "))
    time.sleep(4)
