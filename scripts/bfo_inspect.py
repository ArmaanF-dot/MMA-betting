import glob
import gzip

from bs4 import BeautifulSoup

f = sorted(glob.glob("data/raw/bfo/ufc-3611.html.gz"))[0]
s = BeautifulSoup(gzip.decompress(open(f, "rb").read()).decode("utf-8"), "lxml")
t = s.find_all("table")[1]
rows = t.find("tbody").find_all("tr")
print(len(rows))
for tr in rows[:42]:
    th = tr.find("th")
    tds = tr.find_all("td")
    vals = [td.find("span").get_text(strip=True) if td.find("span") else "" for td in tds[:9]]
    print(tr.get("class"), tr.get("id"), "|", th.get_text(" ", strip=True)[:45] if th else None, "|", {k: v for k, v in (th.attrs if th else {}).items() if k.startswith("data")}, "|", vals)
