"""Model picks for the fights announced so far for UFC 334 (read-only: nothing is logged to the paper files).
Weight class from each fighter's latest bout; rounds assumed (main events 5, others 3); market = median sportsbook price."""
import time
from statistics import median

import duckdb
import httpx

from ufcmodel.ingest.bfo import BASE, HEADERS, _lookup, parse_event
from ufcmodel.reports.fightweek import predict_card
from ufcmodel.reports.livecard import EXCHANGES, weight_class

con = duckdb.connect("data/processed/ufc.duckdb", read_only=True)
alias = _lookup(con)
card = []
for slug, d, main in (("ufc-334-4433", "2026-11-14", "Caio Borralho"), ("ufc-334-4370", "2026-11-15", "Ciryl Gane")):
    html = httpx.get(f"{BASE}/events/{slug}", headers=HEADERS, timeout=60, follow_redirects=True).text
    for na, nb, per in parse_event(html):
        good = {bk: p for bk, p in per.items() if bk not in EXCHANGES and 1.0 <= 1 / p[0] + 1 / p[1] <= 1.15}
        wc = weight_class(con, alias, na) or weight_class(con, alias, nb)
        row = dict(date=d, fighter_a=na, fighter_b=nb, weight_class=wc or "Lightweight", rounds=5 if na in (main, "Amanda Nunes") else 3, wc_known=bool(wc), books=len(good))
        if good:
            row["odds_a"], row["odds_b"] = round(median(p[0] for p in good.values()), 4), round(median(p[1] for p in good.values()), 4)
        card.append(row)
    time.sleep(4)
results, last = predict_card(con, card)
print(f"data ends {last}\n")
for r, c in zip(results, card):
    b = r["b"]
    pa, pm = r["p_model"], r["p_mkt"]
    pick = b["fighter_a"] if pa >= 0.5 else b["fighter_b"]
    print(f"{b['fighter_a']} vs {b['fighter_b']}  ({c['weight_class']}{'' if c['wc_known'] else ' [weight class guessed]'}, {c['rounds']} rounds, {c['date']})")
    print(f"  model: {b['fighter_a']} {pa:.1%} / {b['fighter_b']} {1 - pa:.1%}   pick: {pick} ({max(pa, 1 - pa):.1%})")
    print(f"  Elo: {r['p_elo']:.1%} for {b['fighter_a']};  simulator distance probability: {r['sim']['p_distance']:.1%}")
    if pm is not None:
        print(f"  market (margin removed, {c['books']} books): {b['fighter_a']} {pm:.1%}   blend {r['p']:.1%}   edge on best side {max(r['edges'].values()):+.1%}")
    else:
        print("  no market prices yet")
    for f in r["flags"]:
        print("  flag:", f)
    print()
