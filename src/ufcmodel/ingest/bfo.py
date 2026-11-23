"""Backfill per-sportsbook moneylines from Best Fight Odds event pages into the `odds_books` table.

robots.txt allows /events/ and the terms of service have no scraping clause (checked 2026-10-27). One page at a time with a
pause between requests. A completed event's page shows each book's last line, which is used as the closing line (kind
'close'). The raw page is kept (gzipped) under data/raw/bfo, which is git-ignored: local use only, never redistributed.
Separate table on purpose: `odds_snapshots` is read by the feature store as one price per fighter.
"""
import argparse
import gzip
import re
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from difflib import get_close_matches
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

BASE = "https://www.bestfightodds.com"
HEADERS = {"User-Agent": "ufc-model personal research (non-commercial, slow single-thread)"}
RAW = Path("data/raw/bfo")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", "", s.replace("-", " ")).strip()


def american_to_decimal(txt: str):
    m = re.fullmatch(r"([+-]?)(\d+)", txt.strip().replace("−", "-"))
    if not m:
        return None
    v = int(m.group(2))
    if v == 0:
        return None
    if m.group(1) == "-":
        return 1 + 100 / v
    return 1 + v / 100  # bare numbers and +N are treated as positive prices


def event_urls(since: date, until: date):
    r = httpx.get(f"{BASE}/sitemap-events.xml", headers=HEADERS, timeout=30)
    r.raise_for_status()
    out = []
    for loc, lm in re.findall(r"<loc>([^<]+)</loc><lastmod>([^<]+)</lastmod>", r.text):
        slug = loc.rsplit("/", 1)[-1]
        if not slug.startswith("ufc") or "ultimate-fighter" in slug:
            continue
        d = datetime.strptime(lm[:10], "%Y-%m-%d").date()
        if since <= d <= until:
            out.append((d, loc))
    return sorted(out)


def parse_event(html: str):
    """-> list of (name_a, name_b, {book: (price_a, price_b)}) for the moneyline rows."""
    s = BeautifulSoup(html, "lxml")
    tabs = s.find_all("table")
    if len(tabs) < 2:
        return []
    t = tabs[1]
    # header cells read "Polymarket $25 Bonus i"; keep the name only
    books = [re.split(r"\s+\$\d|\s+Bonus", th.get_text(" ", strip=True))[0] for th in t.find("thead").find_all("th")[1:]]
    rows, fights = [], []
    for tr in t.find("tbody").find_all("tr"):
        if "pr" in (tr.get("class") or []):
            continue
        th = tr.find("th")
        a = th.find("a", href=re.compile(r"^/fighters/")) if th else None
        if a is None:
            continue
        tds = tr.find_all("td")[:len(books)]
        # the price is the first span; a second span holds a line-movement arrow that must not be read as part of it
        rows.append((a.get_text(strip=True), [american_to_decimal(td.find("span").get_text(strip=True)) if td.find("span") else None for td in tds]))
    for (na, pa), (nb, pb) in zip(rows[0::2], rows[1::2]):
        per = {bk: (x, y) for bk, x, y in zip(books, pa, pb) if x and y}
        fights.append((na, nb, per))
    return fights


def parse_props(html: str):
    """-> list of (name_a, name_b, props) where props = {market: {book: (yes_price, no_price)}} for the two clean two-way markets:
    'distance' (fight goes to decision / doesn't) and 'inside_a' / 'inside_b' (that fighter wins inside the distance / doesn't).
    Prop rows follow the pair of fighter rows they belong to."""
    s = BeautifulSoup(html, "lxml")
    tabs = s.find_all("table")
    if len(tabs) < 2:
        return []
    t = tabs[1]
    books = [re.split(r"\s+\$\d|\s+Bonus", th.get_text(" ", strip=True))[0] for th in t.find("thead").find_all("th")[1:]]
    fights = []

    def cells(tr):
        return [american_to_decimal(td.find("span").get_text(strip=True)) if td.find("span") else None for td in tr.find_all("td")[:len(books)]]

    def pair(rows, yes_label, no_label):
        lab = {r[0]: r[1] for r in rows}
        if yes_label in lab and no_label in lab:
            return {bk: (y, n) for bk, y, n in zip(books, lab[yes_label], lab[no_label]) if y and n}
        return {}
    props_rows, names = [], []
    for tr in t.find("tbody").find_all("tr"):
        th = tr.find("th")
        if th is None:
            continue
        if "pr" in (tr.get("class") or []):
            props_rows.append((th.get_text(" ", strip=True), cells(tr)))
            continue
        a = th.find("a", href=re.compile(r"^/fighters/"))
        if a is None:
            continue
        if len(names) == 2:
            fights.append((names[0], names[1], props_rows))
            names, props_rows = [], []
        names.append(a.get_text(strip=True))
    if len(names) == 2:
        fights.append((names[0], names[1], props_rows))
    out = []
    for na, nb, rows in fights:
        sa, sb = norm(na).split()[-1] if norm(na) else "", norm(nb).split()[-1] if norm(nb) else ""
        props = {"distance": pair(rows, "Fight goes to decision", "Fight doesn't go to decision")}
        if sa != sb:
            for key, sur in (("inside_a", sa), ("inside_b", sb)):
                yes = next((r[0] for r in rows if r[0].lower().endswith("wins inside distance") and norm(r[0]).split()[0] == sur), None)
                no = next((r[0] for r in rows if r[0].lower().startswith("not ") and r[0].lower().endswith("inside distance") and norm(r[0]).split()[1] == sur), None)
                props[key] = pair(rows, yes, no) if yes and no else {}
        out.append((na, nb, props))
    return out


def _lookup(con):
    alias = {}
    for a, f in con.execute("SELECT alias, fighter_id FROM fighter_aliases").fetchall():
        alias.setdefault(norm(a), f)
    for f, n in con.execute("SELECT fighter_id, name FROM fighters").fetchall():
        alias.setdefault(norm(n), f)
    return alias


def match_event(con, alias, edate: date, fights):
    """Map each fight to a bout in the database. The sitemap date is only approximate (it can be off by days), so take the
    bouts within 25 days and, for a repeated pairing, the one nearest that date."""
    cand = con.execute("""SELECT b.bout_id, r.fighter_id, u.fighter_id, e.date FROM bouts b JOIN events e USING (event_id)
        JOIN bout_fighter r ON r.bout_id = b.bout_id AND r.corner = 'red' JOIN bout_fighter u ON u.bout_id = b.bout_id AND u.corner = 'blue'
        WHERE e.date BETWEEN ? AND ?""", [edate - timedelta(days=25), edate + timedelta(days=25)]).fetchall()
    pair = {}
    for b, r, u, bd in sorted(cand, key=lambda x: -abs((x[3] - edate).days)):
        pair[frozenset((r, u))] = (b, r, u)
    cand = [(b, r, u) for b, r, u, _ in cand]
    names = {}
    for f, n in con.execute("SELECT fighter_id, name FROM fighters").fetchall():
        names[norm(n)] = f
    window_ids = {x for _, r, u in cand for x in (r, u)}
    window_names = [k for k, v in names.items() if v in window_ids]

    def fid(n):
        k = norm(n)
        if alias.get(k) in window_ids:
            return alias[k]
        close = get_close_matches(k, window_names, n=1, cutoff=0.85)
        return names[close[0]] if close else alias.get(k)
    matched, missed = [], []
    for na, nb, per in fights:
        fa, fb = fid(na), fid(nb)
        hit = pair.get(frozenset((fa, fb))) if fa and fb else None
        if hit is None:
            missed.append((na, nb))
            continue
        bout, _, _ = hit
        matched.append((bout, fa, fb, per))
    return matched, missed, len(cand)


def ensure_table(con):
    con.execute("""CREATE TABLE IF NOT EXISTS odds_books (bout_id VARCHAR, bookmaker VARCHAR, fighter_id VARCHAR,
        price_decimal DOUBLE, kind VARCHAR, source VARCHAR, fetched_at TIMESTAMP)""")


def run(con, since: date, until: date, delay=4.0, limit=None):
    ensure_table(con)
    RAW.mkdir(parents=True, exist_ok=True)
    alias = _lookup(con)
    urls = event_urls(since, until)
    if limit:
        urls = urls[:limit]
    print(f"{len(urls)} UFC event pages between {since} and {until}", flush=True)
    tot_m = tot_x = 0
    for d, url in urls:
        slug = url.rsplit("/", 1)[-1]
        f = RAW / f"{slug[-28:]}.html.gz"   # long scratch paths hit the Windows path limit; the trailing id keeps names unique
        if f.exists():
            html = gzip.decompress(f.read_bytes()).decode("utf-8")
        else:
            r = httpx.get(url, headers=HEADERS, timeout=60, follow_redirects=True)
            low = r.text.lower()
            if r.status_code != 200 or any(m in low for m in ("captcha", "just a moment", "cf-chl", "access denied")):
                print(f"STOP: {url} returned {r.status_code} or a bot check; not working around it", flush=True)
                return
            html = r.text
            f.write_bytes(gzip.compress(html.encode("utf-8")))
            time.sleep(delay)
        matched, missed, ncand = match_event(con, alias, d, parse_event(html))
        if matched:
            con.execute("DELETE FROM odds_books WHERE source = 'bfo' AND bout_id IN (SELECT UNNEST(?::VARCHAR[]))", [[m[0] for m in matched]])
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        rows = []
        for bout, fa, fb, per in matched:
            for bk, (pa, pb) in per.items():
                rows += [(bout, bk, fa, pa, "close", "bfo", now), (bout, bk, fb, pb, "close", "bfo", now)]
        if rows:
            con.executemany("INSERT INTO odds_books VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        tot_m += len(matched)
        tot_x += len(missed)
        print(f"{d} {slug}: {len(matched)} matched of {len(matched) + len(missed)} fights ({ncand} bouts in db); missed {missed[:3]}", flush=True)
    print(f"done: {tot_m} bouts matched, {tot_x} unmatched", flush=True)


if __name__ == "__main__":
    from ufcmodel.db import connect
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2023-06-01")
    ap.add_argument("--until", default=str(date.today()))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--delay", type=float, default=4.0)
    a = ap.parse_args()
    run(connect("data/processed/ufc.duckdb"), date.fromisoformat(a.since), date.fromisoformat(a.until), a.delay, a.limit)
