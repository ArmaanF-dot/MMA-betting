"""Live card: read an upcoming event's odds from Best Fight Odds, build the card CSV, run the fight-week report, and log
timestamped predictions and prices (and the hypothetical paper bets under a rule fixed in advance).

Usage: python -m ufcmodel.reports.livecard <event url> <event date> [--rounds-main 5]
The weight class is taken from each fighter's latest bout in the data; debutants that cannot be placed are listed so they can be
filled in by hand. Number of rounds is assumed 3 (the first-listed fight is assumed to be a 5-round main event): check it.
Paper-bet rule, fixed before any result: flat 10 on a side when the no-market stack's probability x the best price offered
(any listed book) - 1 exceeds 5%.
"""
import argparse
import csv
import gzip
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import httpx
import numpy as np

from ufcmodel.betting.paper import log_recommendation
from ufcmodel.ingest.bfo import HEADERS, _lookup, norm, parse_event
from ufcmodel.reports.fightweek import predict_card, render

EXCHANGES = {"Polymarket", "Kalshi"}   # prediction markets: thin, different margin, not open to UK bettors; kept in the snapshot only
EDGE_RULE = 0.05
STAKE = 10.0


CONF_RULE, CONF_MIN, CONF_HIGH = "C3_v1", 0.70, 0.80
CONF_COLS = ["rule", "ts", "event", "slot", "date", "pick", "opponent", "model_p_pick", "tier", "market_p_pick", "best_price", "best_book",
             "median_price"]


def confident_row(r, c, slug, slot, ts):
    """Forward paper rule C3_v1, fixed before any card was fought: log the model's pick (the no-market stack probability) when it is
    at least 70% confident, flagged '80+' from 80% (the sizes tested in decisions.md Round 15), with the best sportsbook price.
    r: one predict_card result, c: its card row. Returns the log row, or None below 70%."""
    pa = r["p_model"]
    conf = max(pa, 1 - pa)
    if conf < CONF_MIN:
        return None
    a_side = pa >= 0.5
    b = r["b"]
    pm = r["p_mkt"]
    return [CONF_RULE, ts, slug, slot, b["date"], b["fighter_a"] if a_side else b["fighter_b"], b["fighter_b"] if a_side else b["fighter_a"],
            round(conf, 4), "80+" if conf >= CONF_HIGH else "70-80", "" if pm is None else round(pm if a_side else 1 - pm, 4),
            c["best_a"] if a_side else c["best_b"], c["best_a_book"] if a_side else c["best_b_book"], c["odds_a"] if a_side else c["odds_b"]]


def fetch(url):
    r = httpx.get(url, headers=HEADERS, timeout=60, follow_redirects=True)
    low = r.text.lower()
    if r.status_code != 200 or any(m in low for m in ("captcha", "just a moment", "cf-chl", "access denied")):
        raise SystemExit(f"stopped: {url} returned {r.status_code} or a bot check; not working around it")
    return r.text


def weight_class(con, alias, name):
    fid = alias.get(norm(name))
    if not fid:
        return None
    row = con.execute("""SELECT b.weight_class FROM bouts b JOIN events e USING (event_id) JOIN bout_fighter bf ON bf.bout_id = b.bout_id
                         WHERE bf.fighter_id = ? AND b.weight_class IS NOT NULL ORDER BY e.date DESC LIMIT 1""", [fid]).fetchone()
    return row[0] if row else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("date")
    ap.add_argument("--rounds-main", type=int, default=5)
    ap.add_argument("--slot", default="manual", help="which capture time point this is: listed, mon, thu, pre or manual")
    a = ap.parse_args()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    slug = a.url.rsplit("/", 1)[-1]
    html = fetch(a.url)
    Path("data/raw/bfo").mkdir(parents=True, exist_ok=True)
    Path(f"data/raw/bfo/live_{slug[-20:]}_{ts[:10]}.html.gz").write_bytes(gzip.compress(html.encode("utf-8")))
    fights = [f for f in parse_event(html) if f[2]]
    con = duckdb.connect("data/processed/ufc.duckdb")
    alias = _lookup(con)
    con.execute("""CREATE TABLE IF NOT EXISTS odds_live (ts VARCHAR, event VARCHAR, fighter_a VARCHAR, fighter_b VARCHAR,
                   bookmaker VARCHAR, price_a DOUBLE, price_b DOUBLE)""")
    card, notes = [], []
    for k, (na, nb, per) in enumerate(fights):
        good = {bk: p for bk, p in per.items() if 1.0 <= 1 / p[0] + 1 / p[1] <= 1.15}
        if not good:
            notes.append(f"{na} vs {nb}: no usable prices, skipped")
            continue
        for bk, (pa, pb) in good.items():
            con.execute("INSERT INTO odds_live VALUES (?, ?, ?, ?, ?, ?, ?)", [ts, slug, na, nb, bk, pa, pb])
        good = {bk: p for bk, p in good.items() if bk not in EXCHANGES}     # the card and best prices use sportsbooks only
        if not good:
            notes.append(f"{na} vs {nb}: only prediction-market prices, skipped")
            continue
        med =(float(np.median([p[0] for p in good.values()])), float(np.median([p[1] for p in good.values()])))
        best_a = max(good.items(), key=lambda kv: kv[1][0])
        best_b = max(good.items(), key=lambda kv: kv[1][1])
        wc = weight_class(con, alias, na) or weight_class(con, alias, nb)
        if wc is None:
            notes.append(f"{na} vs {nb}: weight class unknown (both look like debutants); set to Lightweight, fix by hand")
            wc = "Lightweight"
        card.append(dict(date=a.date, fighter_a=na, fighter_b=nb, weight_class=wc, rounds=a.rounds_main if k == 0 else 3,
                         odds_a=round(med[0], 4), odds_b=round(med[1], 4), best_a=round(best_a[1][0], 4), best_a_book=best_a[0],
                         best_b=round(best_b[1][1], 4), best_b_book=best_b[0], books=len(good)))
    path = Path(f"cards/{a.date}_bfo_live.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write(f"# Live odds from Best Fight Odds read {ts}: odds_a/odds_b = median decimal price across books, best_* = best price listed. "
                f"Rounds assumed (first fight {a.rounds_main}, others 3).\n")
        w = csv.DictWriter(f, fieldnames=list(card[0]))
        w.writeheader()
        w.writerows(card)
    results, last = predict_card(con, card)
    Path(f"docs/fightweek_{a.date}.html").write_text(render(results, last, f"Fight-week report, {a.date} (prices read {ts})"), encoding="utf-8")
    Path("data/paper").mkdir(parents=True, exist_ok=True)
    pred_path = Path(f"data/paper/predictions_{a.date}.csv")
    if pred_path.exists():                      # files written before the slot column existed: their rows were manual captures
        with open(pred_path, newline="", encoding="utf-8") as f:
            old = list(csv.reader(f))
        if old and old[0][-1] != "slot":
            with open(pred_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows([old[0] + ["slot"]] + [r + ["manual"] for r in old[1:]])
    new = not pred_path.exists()
    n_bets = 0
    with open(pred_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts", "event", "fighter_a", "fighter_b", "p_a_model_no_market", "p_a_blend", "p_a_elo", "p_a_market_devig", "median_a", "median_b",
                        "best_a", "best_a_book", "best_b", "best_b_book", "books", "slot"])
        for r, c in zip(results, card):
            b = r["b"]
            w.writerow([ts, slug, b["fighter_a"], b["fighter_b"], round(r["p_model"], 4), round(r["p"], 4), round(r["p_elo"], 4),
                        "" if r["p_mkt"] is None else round(r["p_mkt"], 4), c["odds_a"], c["odds_b"], c["best_a"], c["best_a_book"], c["best_b"], c["best_b_book"], c["books"], a.slot])
            for side, p, price, book, who in (("A", r["p_model"], c["best_a"], c["best_a_book"], b["fighter_a"]),
                                              ("B", 1 - r["p_model"], c["best_b"], c["best_b_book"], b["fighter_b"])):
                if p * price - 1 > EDGE_RULE:
                    log_recommendation("data/paper/paper_log.csv", ts, f"{slug}@{a.slot}", f"{b['fighter_a']} vs {b['fighter_b']}", side, book, price, p)
                    n_bets += 1
                    notes.append(f"paper bet (flat {STAKE:.0f}): {who} at {price} ({book}), model {p:.1%}, edge {p * price - 1:+.1%}")
    conf_path = Path("data/paper/confident_picks.csv")
    n_conf = 0
    with open(conf_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if f.tell() == 0:
            w.writerow(CONF_COLS)
        for r, c in zip(results, card):
            row = confident_row(r, c, slug, a.slot, ts)
            if row:
                w.writerow(row)
                n_conf += 1
                notes.append(f"{CONF_RULE}: {row[5]} over {row[6]}, model {row[7]:.1%} [{row[8]}], best {row[10]} ({row[11]})")
    con.close()
    print(f"{n_conf} confident picks logged to {conf_path}")
    print(f"{len(card)} fights, prices read {ts}; card {path}; report docs/fightweek_{a.date}.html; predictions {pred_path}; {n_bets} paper bets")
    for n in notes:
        print(" -", n)
    for r in results:
        b = r["b"]
        print(f"{b['fighter_a']:24s} vs {b['fighter_b']:24s} model {r['p_model']:.1%}  blend {r['p']:.1%}  market {('n/a' if r['p_mkt'] is None else format(r['p_mkt'], '.1%'))}  flags {len(r['flags'])}")


if __name__ == "__main__":
    main()
