import re

import httpx
from bs4 import BeautifulSoup

H = {"User-Agent": "ufc-model personal research (non-commercial, slow single-thread)"}
r = httpx.get("https://www.bestfightodds.com/sitemap-events.xml", headers=H, timeout=30)
print(r.status_code, len(r.text))
locs = re.findall(r"<loc>([^<]+)</loc>", r.text)
ev = [x for x in locs if "/events/" in x]
print("event urls:", len(ev), ev[:3], ev[-3:])
print("ufc-ish:", len([x for x in ev if "/ufc" in x.lower()]))
print(r.text[:500])
open("data/raw/bfo/sitemap_events.txt", "w").write("\n".join(ev))

s = BeautifulSoup(open("data/raw/bfo/ufc-333-4321.html", encoding="utf-8").read(), "lxml")
print("title:", s.title.string if s.title else None)
print("h1:", [h.get_text(" ", strip=True) for h in s.find_all(["h1", "h2"])][:6])
txt = s.get_text(" ", strip=True)
for m in re.finditer(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}(st|nd|rd|th)?,? 20\d\d", txt):
    print("date text:", txt[max(0, m.start() - 40):m.end() + 20]); break
print([ (m.group(0)) for m in re.finditer(r'<meta[^>]+(date|published|og:title)[^>]*>', str(s))][:5])
