"""Feasibility probe for the profit plan: how is an old (2015) event page laid out? One request, saved for later parsing work."""
import gzip
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from ufcmodel.ingest.bfo import HEADERS

url = "https://www.bestfightodds.com/events/ufc-190-rousey-vs-correia-960"
f = Path("data/raw/bfo/probe_ufc190.html.gz")
if not f.exists():
    r = httpx.get(url, headers=HEADERS, timeout=60, follow_redirects=True)
    f.write_bytes(gzip.compress(r.text.encode("utf-8")))
html = gzip.decompress(f.read_bytes()).decode("utf-8")
s = BeautifulSoup(html, "lxml")
tabs = s.find_all("table")
print("tables:", len(tabs), [t.get("class") for t in tabs])
t = tabs[1]
print("header:", [th.get_text(" ", strip=True)[:16] for th in t.find("thead").find_all("th")])
tr = [r for r in t.find("tbody").find_all("tr") if "pr" not in (r.get("class") or [])][0]
print(str(tr)[:1800])
