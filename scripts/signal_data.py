"""Export what the predictor UI shows: every upcoming UFC card on the odds site (next 30 days), the model's read of each fight, the staking rule
applied to a GBP 50 budget per card, expected earnings under two views (the model is right / the market is right), the capture schedule,
the paper-test picks and the evidence table. Writes ufc-ui/data.json. Read-only apart from that file; one polite request per page.
Staking rule (decisions.md rounds 5 to 12, unchanged): p* = the model blended with the market (the stack's own blend weight); a side is bet only
if p* x best sportsbook price - 1 exceeds 3%; stake = quarter Kelly x budget, halved for a fighter with under 3 earlier UFC fights, halved again
if p* is more than 15 points from the market, at most 20% of the budget per fight, scaled down to the budget."""
import csv
import json
import math
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import httpx
import numpy as np

from ufcmodel.ingest.bfo import BASE, HEADERS, _lookup, parse_event
from ufcmodel.reports.capture import load_state, parse_upcoming, slot_times
from ufcmodel.reports.fightweek import predict_card
from ufcmodel.reports.livecard import EXCHANGES, weight_class

BUDGET, KAPPA, EDGE_MIN, CAP_F, HORIZON_DAYS = 50.0, 1.0, 0.03, 0.20, 30   # KAPPA raised from 0.25 to 1.0 on request (decisions.md Round 17)
OUT = Path("ufc-ui/data.json")
now = datetime.now()
con = duckdb.connect("data/processed/ufc.duckdb", read_only=True)
alias = _lookup(con)
rng = np.random.default_rng(0)


def fetch(url):
    r = httpx.get(url, headers=HEADERS, timeout=60, follow_redirects=True)
    low = r.text.lower()
    if r.status_code != 200 or any(m in low for m in ("captcha", "just a moment", "cf-chl", "access denied")):
        raise SystemExit(f"stopped: {url} returned {r.status_code} or a bot check; not working around it")
    return r.text


# ---- which cards -----------------------------------------------------------------------------------------------------------
front = fetch(BASE + "/")
events = [e for e in parse_upcoming(front, now.date()) if 0 <= (date.fromisoformat(e["date"]) - now.date()).days <= HORIZON_DAYS]
groups = {}
for e in events:                                           # the site splits one card over two pages sometimes (UFC 334): merge by name
    key = e["slug"].rsplit("-", 1)[0]
    groups.setdefault(key, []).append(e)
state = load_state()
cards_out = []
for key, evs in groups.items():
    time.sleep(4)
    fights_raw, dates = [], []
    for e in evs:
        html = fetch(e["url"])
        dates.append(e["date"])
        for k, (na, nb, per) in enumerate(parse_event(html)):
            fights_raw.append((na, nb, per, k == 0))
        time.sleep(4)
    card, meta = [], []
    for na, nb, per, first in fights_raw:
        good = {bk: p for bk, p in per.items() if bk not in EXCHANGES and 1.0 <= 1 / p[0] + 1 / p[1] <= 1.15}
        wc = weight_class(con, alias, na) or weight_class(con, alias, nb)
        row = dict(date=min(dates), fighter_a=na, fighter_b=nb, weight_class=wc or "Lightweight", rounds=5 if (first or "Nunes" in na) else 3)
        info = dict(wc_known=bool(wc), books=len(good))
        if good:
            row["odds_a"] = round(float(np.median([p[0] for p in good.values()])), 4)
            row["odds_b"] = round(float(np.median([p[1] for p in good.values()])), 4)
            ba, bb = max(good.items(), key=lambda kv: kv[1][0]), max(good.items(), key=lambda kv: kv[1][1])
            info.update(best_a=round(ba[1][0], 3), best_a_book=ba[0], best_b=round(bb[1][1], 3), best_b_book=bb[0], med_a=row["odds_a"], med_b=row["odds_b"])
        card.append(row)
        meta.append(info)
    results, last = predict_card(con, card)
    fights = []
    for r, m in zip(results, meta):
        b = r["b"]
        pa_model, pa_blend, pa_mkt = r["p_model"], r["p"], r["p_mkt"]
        f = dict(a=b["fighter_a"], b=b["fighter_b"], wc=b["weight_class"], rounds=int(b["rounds"]), wc_known=m["wc_known"], books=m["books"],
                 p_model=round(pa_model, 4), p_blend=round(pa_blend, 4), p_mkt=None if pa_mkt is None else round(pa_mkt, 4), p_elo=round(r["p_elo"], 4),
                 dist=round(float(r["sim"]["p_distance"]), 4), flags=r["flags"], coverage=list(r["coverage"]),
                 drivers=[[n, round(float(v), 1)] for n, v in sorted(r["drivers"], key=lambda t: -abs(t[1]))[:3]])
        f.update({k: m[k] for k in ("best_a", "best_a_book", "best_b", "best_b_book", "med_a", "med_b") if k in m})
        # the model's pick and the paper-test tier
        conf = max(pa_model, 1 - pa_model)
        f["pick"] = dict(fighter=f["a"] if pa_model >= 0.5 else f["b"], side="A" if pa_model >= 0.5 else "B", conf=round(conf, 4),
                         tier="80+" if conf >= 0.8 else ("70-80" if conf >= 0.7 else None))
        # staking candidates
        f["cands"] = []
        if pa_mkt is not None and "best_a" in f:
            thin = min(f["coverage"]) < 3
            for side, p, pm, price, book, who in (("A", pa_blend, pa_mkt, f["best_a"], f["best_a_book"], f["a"]), ("B", 1 - pa_blend, 1 - pa_mkt, f["best_b"], f["best_b_book"], f["b"])):
                edge = p * price - 1
                mult = (0.5 if thin else 1.0) * (0.5 if abs(p - pm) > 0.15 else 1.0)
                kelly = max(0.0, KAPPA * edge / (price - 1) * BUDGET * mult) if edge > 0 else 0.0
                f["cands"].append(dict(side=side, fighter=who, p=round(p, 4), pm=round(pm, 4), price=price, book=book, edge=round(edge, 4), thin=thin,
                                       raw_stake=round(min(CAP_F * BUDGET, kelly), 2) if edge > EDGE_MIN else 0.0))
        fights.append(f)
    # scale to the budget
    tot = sum(c["raw_stake"] for f in fights for c in f["cands"])
    scale = min(1.0, BUDGET / tot) if tot > 0 else 0.0
    for f in fights:
        f["bet"] = None
        best = max(f["cands"], key=lambda c: c["raw_stake"], default=None)
        if best and best["raw_stake"] > 0:
            f["bet"] = dict(best, stake=round(best["raw_stake"] * scale, 2))
        elif f["cands"]:
            top = max(f["cands"], key=lambda c: c["edge"])
            f["why_pass"] = ("edge %+.1f%% is below the 3%% needed" % (100 * top["edge"])) + ("; thin data on a fighter" if top["thin"] else "")
        else:
            f["why_pass"] = "no sportsbook price yet"
    bets = [f["bet"] for f in fights if f["bet"]]
    staked = sum(b["stake"] for b in bets)

    def simulate(view):
        if not bets:
            return None
        n = 20000
        pnl = np.zeros(n)
        for b in bets:
            p = b["p"] if view == "model" else b["pm"]
            win = rng.random(n) < p
            pnl += np.where(win, b["stake"] * (b["price"] - 1), -b["stake"])
        edges = np.linspace(min(pnl.min(), -staked), pnl.max() + 0.01, 25)
        h, _ = np.histogram(pnl, bins=edges)
        return dict(ev=float(pnl.mean()), p_profit=float((pnl > 0).mean()), p05=float(np.percentile(pnl, 5)), p95=float(np.percentile(pnl, 95)),
                    edges=[round(float(x), 2) for x in edges], counts=[round(float(c) / n, 4) for c in h])
    sim_model, sim_mkt = simulate("model"), simulate("market")
    # paper-test picks: at least 70% confident, flat 10 on the best price
    picks = []
    for f in fights:
        if f["pick"]["tier"]:
            side = f["pick"]["side"]
            price = f.get("best_a" if side == "A" else "best_b")
            if price:
                picks.append(dict(fighter=f["pick"]["fighter"], vs=f["b"] if side == "A" else f["a"], conf=f["pick"]["conf"], tier=f["pick"]["tier"], price=price,
                                  book=f["best_a_book" if side == "A" else "best_b_book"], stake=10.0))
    d0 = date.fromisoformat(min(dates))
    st_ev = next((v for k, v in state["events"].items() if k.rsplit("-", 1)[0] == key), None)
    times = slot_times(d0 if len(set(dates)) == 1 else date.fromisoformat(max(dates)))
    def slot_status(raw, due):
        raw = raw or ""
        for word in ("done", "missed", "retry", "gave"):
            if raw.startswith(word):
                return word
        return "due" if due else "upcoming"
    slots = {s: dict(time=t.isoformat(timespec="minutes"), status=slot_status((st_ev or {}).get("slots", {}).get(s), t <= now)) for s, t in times.items()}
    slots["listed"] = dict(time=None, status=slot_status((st_ev or {}).get("slots", {}).get("listed"), False))
    cards_out.append(dict(key=key, name=evs[0]["slug"].rsplit("-", 1)[0].replace("-", " ").upper().replace("UFC VEGAS", "UFC Vegas"),
                          dates=sorted(set(dates)), days=(d0 - now.date()).days, n_fights=len(fights), n_priced=sum(1 for f in fights if f["cands"]), last_data=last,
                          fights=fights, staked=round(staked, 2), bets=len(bets), sim_model=sim_model, sim_market=sim_mkt, picks=picks, slots=slots,
                          ev_model=None if not sim_model else round(sim_model["ev"], 2), ev_market=None if not sim_mkt else round(sim_mkt["ev"], 2)))
cards_out.sort(key=lambda c: c["dates"][0])

# ---- paper ledger: the staking rule's bets per card, frozen once the card's date has passed, then settled against real results ----------
SCALE = 1000.0 / BUDGET                       # the bar shows a 1,000 budget per event; stakes scale linearly from the 50 budget
LEDGER = Path("data/paper/ledger.json")
ledger = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
today = now.date().isoformat()
for c in cards_out:
    if c["dates"][-1] >= today:               # still to come: the ledger holds the bets as they stand now
        ledger[c["key"]] = dict(name=c["name"], date=c["dates"][-1], bets=[
            dict(fighter=f["bet"]["fighter"], vs=f["b"] if f["bet"]["side"] == "A" else f["a"], price=f["bet"]["price"], book=f["bet"]["book"], stake=f["bet"]["stake"])
            for f in c["fights"] if f["bet"]])
LEDGER.parent.mkdir(parents=True, exist_ok=True)
LEDGER.write_text(json.dumps(ledger, indent=1), encoding="utf-8")


def settle(bet, d):
    """'won' / 'lost' / 'void' for a ledger bet once the results data has the fight, else None."""
    from ufcmodel.ingest.bfo import norm
    fa, fb = alias.get(norm(bet["fighter"])), alias.get(norm(bet["vs"]))
    if not (fa and fb):
        return None
    d0 = date.fromisoformat(d)
    row = con.execute("""SELECT x.result FROM bout_fighter x JOIN bout_fighter y ON y.bout_id = x.bout_id AND y.fighter_id = ? JOIN bouts b ON b.bout_id = x.bout_id
                         JOIN events e ON e.event_id = b.event_id WHERE x.fighter_id = ? AND e.date BETWEEN ? AND ? LIMIT 1""", [fb, fa, d0 - timedelta(days=3), d0 + timedelta(days=3)]).fetchone()
    return None if not row else {"win": "won", "loss": "lost"}.get(row[0], "void")


settled_events, r_bets, r_staked, r_profit, r_wait = 0, 0, 0.0, 0.0, 0
for key, ev in ledger.items():
    if ev["date"] >= today or not ev["bets"]:
        continue
    res = [settle(b, ev["date"]) for b in ev["bets"]]
    if any(r is None for r in res):
        r_wait += sum(1 for r in res if r is None)
        continue
    settled_events += 1
    for b, r in zip(ev["bets"], res):
        r_bets += 1
        r_staked += b["stake"] * SCALE
        r_profit += b["stake"] * SCALE * (b["price"] - 1) if r == "won" else (-b["stake"] * SCALE if r == "lost" else 0.0)
up = [c for c in cards_out if c["dates"][-1] >= today]
bar = dict(per_event=1000, asof=now.isoformat(timespec="minutes"),
           upcoming=dict(events=len(up), with_bets=sum(1 for c in up if c["bets"]), staked=round(sum(c["staked"] for c in up) * SCALE, 2),
                         ev_model=round(sum((c["ev_model"] or 0.0) for c in up) * SCALE, 2), ev_market=round(sum((c["ev_market"] or 0.0) for c in up) * SCALE, 2)),
           realised=dict(events=settled_events, bets=r_bets, staked=round(r_staked, 2), profit=round(r_profit, 2), awaiting=r_wait,
                         first=min((c["dates"][-1] for c in up), default=None)))

picks_logged = 0
pth = Path("data/paper/confident_picks.csv")
if pth.exists():
    picks_logged = len(list(csv.DictReader(open(pth, encoding="utf-8"))))
evidence = [
    dict(label="Model's pick in every fight, typical price", v=-5.4, lo=-12.7, hi=2.3, n="1,150 bets, 2023-25", kind="test"),
    dict(label="Model's pick, best price at any book", v=0.4, lo=-7.6, hi=8.2, n="1,150 bets, 2023-25", kind="test"),
    dict(label="Market favourite in every fight, typical price", v=-1.3, lo=-5.2, hi=2.6, n="1,150 bets, 2023-25", kind="test"),
    dict(label="Value bets only (edge above 5%), typical price", v=-11.3, lo=-20.9, hi=-2.1, n="835 bets, 2023-25", kind="test"),
    dict(label="This staking rule, 50 per card, best price", v=3.7, lo=-10, hi=17, n="102 cards, 2023-25", kind="test"),
    dict(label="Picks at 70%+ confidence, typical price", v=6.6, lo=0, hi=13, n="254 bets, found after the fact", kind="lead"),
    dict(label="Picks at 80%+ confidence, typical price", v=8.4, lo=-4, hi=20, n="52 bets, found after the fact", kind="lead"),
    dict(label="Opening-line rule at the very first price", v=5.1, lo=-2.4, hi=12.9, n="1,045 bets, 2022-25", kind="untradable"),
    dict(label="Same rule at a mid-week price", v=-1.3, lo=-9.1, hi=6.5, n="1,044 bets, 2022-25", kind="untradable"),
]
res_path = Path("data/paper/results.json")           # written by scripts/grade_results.py
results = json.loads(res_path.read_text(encoding="utf-8")) if res_path.exists() else dict(cards=[])
picks_graded = sum(1 for c in results["cards"] for p in c["picks"] if p["status"] in ("won", "lost"))
out = dict(bar=bar, results=results, asof=now.isoformat(timespec="minutes"), budget=BUDGET, kelly=KAPPA, edge_min=EDGE_MIN, cap=CAP_F, cards=cards_out, evidence=evidence,
           gap=dict(model_ll=0.6421, market_ll=0.6118, diff=0.0303, lo=0.0224, hi=0.0380, n=4923), forward=dict(logged=picks_logged, graded=picks_graded, needed=150),
           backtest=dict(per_card=0.44, events=102, roi=3.7, lo=-10, hi=17))
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
print(f"{len(cards_out)} cards; " + "; ".join(f"{c['name']} {c['dates']}: {c['n_fights']} fights, {c['n_priced']} priced, {c['bets']} bets, staked {c['staked']}" for c in cards_out))

