"""Opening and closing lines for every fight, from Best Fight Odds fighter pages (same permission checks and politeness as ingest/bfo.py).

A fighter page lists each fight as two rows (the fighter and the opponent) with the opening price, the closing range across books
(lowest and highest), a sparkline of the price history and the percentage move. Every fight shows on both fighters' pages, so a
fighter is skipped once all their fights since `since` are covered by pages already read. Raw pages are cached gzipped under
data/raw/bfo/fighters (git-ignored, local only).
"""
import argparse
import gzip
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from ufcmodel.ingest.bfo import BASE, HEADERS, _lookup, american_to_decimal, norm

RAW = Path("data/raw/bfo/fighters")
DATE = re.compile(r"([A-Z][a-z]{2}) (\d{1,2})(?:st|nd|rd|th) (\d{4})")


def _price(cell):
    span = cell.find("span") if cell else None
    return american_to_decimal(span.get_text(strip=True)) if span else None


def _matchup_id(el):
    """The site's matchup id (same on the event page); ids grow with the time a matchup was created, which dates a late replacement."""
    m = re.match(r"\[(\d+),", el.get("data-li", "")) if el is not None else None
    return int(m.group(1)) if m else None


def parse_fighter(html: str):
    """-> list of dict(fighter, opponent, event, date, open_a, low_a, high_a, open_b, low_b, high_b, sparkline) for one page.
    Prices are decimal; 'a' is the page's fighter and 'b' the opponent. Fights without an opening price are kept with None."""
    t = BeautifulSoup(html, "lxml").find("table", class_="team-stats-table")
    if t is None:
        return []
    out, event, when = [], None, None
    rows = t.find_all("tr")
    k = 0
    while k < len(rows):
        tr = rows[k]
        cls = tr.get("class") or []
        if "event-header" in cls:
            a = tr.find("a")
            event = a.get_text(strip=True) if a else tr.get_text(strip=True)
            m = DATE.search(tr.get_text(" ", strip=True))
            when = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%b %d %Y").date() if m else None
        elif "main-row" in cls and k + 1 < len(rows):
            opp = rows[k + 1]
            ta, tb = tr.find_all("td"), opp.find_all("td")
            na, nb = tr.find("th"), opp.find("th")
            chart = tr.find("td", class_="chart-cell")
            out.append(dict(
                fighter=na.get_text(strip=True) if na else None, opponent=nb.get_text(strip=True) if nb else None,
                event=event, date=when,
                open_a=_price(ta[0]) if ta else None, low_a=_price(ta[1]) if len(ta) > 1 else None, high_a=_price(ta[3]) if len(ta) > 3 else None,
                open_b=_price(tb[0]) if tb else None, low_b=_price(tb[1]) if len(tb) > 1 else None, high_b=_price(tb[3]) if len(tb) > 3 else None,
                sparkline=(chart.get("data-sparkline") if chart is not None else None),
                mu=_matchup_id(chart if chart is not None else tr.find("span", class_="teamPercChange"))))
            k += 1
        k += 1
    return out


def candidate_pages(con, since: date):
    """[(url, fighter_id, last_bout_date)] for database fighters with a bout since `since`, newest first, from the site's fighter sitemap."""
    sm = Path("data/raw/bfo/sitemap_fighters.txt")
    if not sm.exists():
        r = httpx.get(f"{BASE}/sitemap-teams.xml", headers=HEADERS, timeout=60)
        r.raise_for_status()
        sm.write_text("\n".join(re.findall(r"<loc>([^<]+)</loc>", r.text)))
    by_name = {}
    for u in sm.read_text().split():
        slug = u.rsplit("/", 1)[-1]
        by_name.setdefault(norm(re.sub(r"-\d+$", "", slug)), []).append(u)
    alias = _lookup(con)
    rows = con.execute("""SELECT bf.fighter_id, f.name, max(e.date) FROM bout_fighter bf JOIN bouts b USING (bout_id) JOIN events e USING (event_id)
                          JOIN fighters f ON f.fighter_id = bf.fighter_id WHERE e.date >= ? GROUP BY 1, 2""", [since]).fetchall()
    out = []
    for fid, name, last in rows:
        urls = list(by_name.get(norm(name), []))
        for a, f in alias.items():
            if f == fid and a != norm(name):
                urls += by_name.get(a, [])
        for u in dict.fromkeys(urls):
            out.append((u, fid, last))
    return sorted(out, key=lambda x: x[2], reverse=True)


def cache_path(url):
    return RAW / f"{url.rsplit('/', 1)[-1][-24:]}.html.gz"


def run(con, since: date, delay=4.0, limit=None):
    RAW.mkdir(parents=True, exist_ok=True)
    alias = _lookup(con)
    todo = candidate_pages(con, since)
    bouts = {}   # fighter_id -> [(pair, date)] from the database
    for b, fa, fb, d in con.execute("""SELECT b.bout_id, r.fighter_id, u.fighter_id, e.date FROM bouts b JOIN events e USING (event_id)
        JOIN bout_fighter r ON r.bout_id = b.bout_id AND r.corner = 'red' JOIN bout_fighter u ON u.bout_id = b.bout_id AND u.corner = 'blue'
        WHERE e.date >= ?""", [since]).fetchall():
        for f in (fa, fb):
            bouts.setdefault(f, []).append((frozenset((fa, fb)), d))
    covered = set()

    def mark(html):
        for r in parse_fighter(html):
            fa, fb = alias.get(norm(r["fighter"] or "")), alias.get(norm(r["opponent"] or ""))
            if fa and fb and r["date"]:
                covered.add((frozenset((fa, fb)), r["date"]))

    def is_covered(fid):
        return all(any((p, d + timedelta(days=k)) in covered for k in (-1, 0, 1)) for p, d in bouts.get(fid, []))
    for u, _, _ in todo:                       # what earlier runs already read
        if cache_path(u).exists():
            mark(gzip.decompress(cache_path(u).read_bytes()).decode("utf-8"))
    print(f"{len(todo)} candidate pages, {sum(cache_path(u).exists() for u, _, _ in todo)} already cached", flush=True)
    n = skipped = 0
    for u, fid, last in todo:
        if cache_path(u).exists():
            continue
        if is_covered(fid):
            skipped += 1
            continue
        r = httpx.get(u, headers=HEADERS, timeout=60, follow_redirects=True)
        low = r.text.lower()
        if r.status_code != 200 or any(m in low for m in ("captcha", "just a moment", "cf-chl", "access denied")):
            print(f"STOP: {u} returned {r.status_code} or a bot check; not working around it", flush=True)
            return
        cache_path(u).write_bytes(gzip.compress(r.text.encode("utf-8")))
        mark(r.text)
        n += 1
        if n % 25 == 0:
            print(f"fetched {n}, skipped as covered {skipped}, covered fights {len(covered)}", flush=True)
        if limit and n >= limit:
            break
        time.sleep(delay)
    print(f"done: fetched {n}, skipped as covered {skipped}", flush=True)


if __name__ == "__main__":
    import duckdb
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2014-06-01")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--delay", type=float, default=4.0)
    a = ap.parse_args()
    con = duckdb.connect("data/processed/ufc.duckdb", read_only=True)   # read only: a long crawl must not hold the database's write lock
    run(con, date.fromisoformat(a.since), a.delay, a.limit)
