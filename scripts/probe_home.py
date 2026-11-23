import glob
import gzip
import re

import httpx
from bs4 import BeautifulSoup

from ufcmodel.ingest.bfo import HEADERS

live = sorted(glob.glob("data/raw/bfo/live_*.html.gz"))[-1]
html = gzip.decompress(open(live, "rb").read()).decode("utf-8")
print("live page:", live, len(html))
for pat in (r'"startDate"\s*:\s*"[^"]+"', r'startDate[^,]{0,60}', r'datetime="[^"]+"', r'(?:Nov|Oct)[a-z]* \d{1,2}(?:st|nd|rd|th)?,? 20\d\d[^<]{0,40}', r'\d{1,2}:\d{2}\s?(?:AM|PM|am|pm)[^<]{0,20}'):
    m = re.findall(pat, html)
    print(pat[:30], "->", m[:5])
r = httpx.get("https://www.bestfightodds.com/", headers=HEADERS, timeout=60)
print("home", r.status_code, len(r.text))
s = BeautifulSoup(r.text, "lxml")
links = [(a.get_text(" ", strip=True), a["href"]) for a in s.find_all("a", href=re.compile(r"^/events/"))]
print(len(links), links[:14])
t = s.find("table", class_=re.compile("content-list|event"))
print("tables:", [x.get("class") for x in s.find_all("table")][:6])
for div in s.find_all(class_=re.compile("event|card"))[:6]:
    print(div.name, div.get("class"), div.get_text(" ", strip=True)[:90])
