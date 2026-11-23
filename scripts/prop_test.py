"""Do the method/distance models beat real prop prices, and what does a 2-fight parlay return? Development period only (2023-06 to
2025-10-18). Thresholds and rules were fixed before looking: edge above 0, 5, 10% (flat 10), the two highest-edge fights per event
for the parlay. Prices: sportsbooks only (Polymarket and Kalshi excluded), 'median' across books and 'best' of any book."""
import pickle

import duckdb
import numpy as np

from ufcmodel.eval import metrics as M

STAKE = 10.0
EXCH = {"Polymarket", "Kalshi"}
rng = np.random.default_rng(0)
c = duckdb.connect("data/processed/ufc.duckdb", read_only=True)
mod = pickle.load(open("data/processed/prop_model.pkl", "rb"))
meth = dict(c.execute("select bout_id, method from bouts").fetchall())
red = {b: f for b, f in c.execute("select bout_id, fighter_id from bout_fighter where corner='red'").fetchall()}
winner = {b: (f, cn) for b, f, cn in c.execute("select bout_id, fighter_id, corner from bout_fighter where result='win'").fetchall()}
props = {}
for b, bk, mk, fid, y, n in c.execute("select bout_id, bookmaker, market, fighter_id, yes_price, no_price from odds_props").fetchall():
    if bk in EXCH or not (1 < y < 50 and 1 < n < 50) or not 1.0 <= 1 / y + 1 / n <= 1.15:
        continue
    props.setdefault((b, mk, fid), []).append((y, n))
FIN = ("KO/TKO", "Submission")


def build(market):
    items = []
    for (b, mk, fid), pr in props.items():
        if mk != market or len(pr) < (3 if market == "distance" else 2) or b not in mod or meth.get(b) not in FIN + ("Decision",):   # few books list 'inside distance'
            continue
        m = mod[b]
        pm = float(np.median([(1 / y) / (1 / y + 1 / n) for y, n in pr]))
        if market == "distance":
            yv, pmods = float(meth[b] == "Decision"), dict(sim=m["dist_sim"], dir=m["dist_dir"], base=m["dist_base"])
        else:
            if b not in winner:
                continue
            side = "a" if fid == red[b] else "b"
            yv = float(winner[b][0] == fid and meth[b] in FIN)
            pmods = dict(sim=m[f"{side}_in_sim"], dir=m[f"{side}_in_dir"], base=m[f"{side}_in_base"])
        if any(v is None for v in pmods.values()):
            continue
        pmods["blend"] = (pmods["sim"] + pmods["dir"]) / 2
        items.append(dict(b=b, date=m["date"], y=yv, mk=pm, mods=pmods, med=(float(np.median([p[0] for p in pr])), float(np.median([p[1] for p in pr]))),
                          best=(max(p[0] for p in pr), max(p[1] for p in pr))))
    return items


def evaluate(label, items):
    y = np.array([i["y"] for i in items])
    pm = np.array([i["mk"] for i in items])
    base = M.per_bout_log_loss(pm, y)
    print(f"\n== {label}: {len(items)} markets, {len({i['b'] for i in items})} fights, event rate {y.mean():.1%}, market average {pm.mean():.1%}")
    print(f"market log loss {M.log_loss(pm, y):.4f}")
    for nm in ("sim", "dir", "blend", "base"):
        p = np.array([i["mods"][nm] for i in items])
        ll = M.per_bout_log_loss(p, y)
        dm, lo, hi = M.paired_bootstrap_diff(ll, base)
        print(f"  {nm:6s} log loss {M.log_loss(p, y):.4f}  minus market {dm:+.4f} [{lo:+.4f}, {hi:+.4f}]  (positive = model worse)  average p {p.mean():.1%}")
    for nm in ("blend",):
        for price in ("med", "best"):
            for thr in (0.0, 0.05, 0.10):
                pr = []
                for i in items:
                    p = i["mods"][nm]
                    ey, en = p * i[price][0] - 1, (1 - p) * i[price][1] - 1
                    if max(ey, en) > thr:
                        yes = ey >= en
                        won = (i["y"] == 1) if yes else (i["y"] == 0)
                        pr.append(STAKE * ((i[price][0] if yes else i[price][1]) - 1) if won else -STAKE)
                pr = np.array(pr)
                if len(pr):
                    mm = pr[rng.integers(0, len(pr), (3000, len(pr)))].mean(axis=1) / STAKE
                    print(f"  bet the {nm} model, {price} price, edge > {thr:.0%}: bets {len(pr):4d}  profit {pr.sum():+9,.2f}  ROI {pr.mean()/STAKE:+.1%} [{np.percentile(mm,2.5):+.1%}, {np.percentile(mm,97.5):+.1%}]")


dist_items = build("distance")
evaluate("Goes the distance (fight goes to decision)", dist_items)
evaluate("Fighter wins inside the distance", build("inside"))

print("\n== Blind 'goes to decision' bet by year (no model): the market's average vs what happened")
for yr in sorted({i["date"][:4] for i in dist_items}):
    its = [i for i in dist_items if i["date"][:4] == yr]
    row = f"  {yr}: {len(its):4d} fights, decisions {np.mean([i['y'] for i in its]):.1%}, market {np.mean([i['mk'] for i in its]):.1%}, model(blend) {np.mean([i['mods']['blend'] for i in its]):.1%}"
    for price in ("med", "best"):
        pr = np.array([STAKE * (i[price][0] - 1) if i["y"] == 1 else -STAKE for i in its])
        row += f"; yes at {price} price ROI {pr.mean()/STAKE:+.1%}"
    print(row)
for sched in (3, 5):
    its = [i for i in dist_items if mod[i["b"]]["sched"] == sched]
    if its:
        print(f"  {sched}-round fights: {len(its)}, decisions {np.mean([i['y'] for i in its]):.1%}, market {np.mean([i['mk'] for i in its]):.1%}")

# ---- two-fight parlays on moneylines, same event ---------------------------------------------------------------------------
pred = {}
for b, p in c.execute("select bout_id, p_red from predictions_ml where model = 'stack'").fetchall():
    pred[b] = p
books = {}
for b, bk, f, p in c.execute("select bout_id, bookmaker, fighter_id, price_decimal from odds_books").fetchall():
    if bk not in EXCH:
        books.setdefault(b, {}).setdefault(bk, {})[f] = p
blue = {b: f for b, f in c.execute("select bout_id, fighter_id from bout_fighter where corner='blue'").fetchall()}
ev_of = dict(c.execute("select b.bout_id, b.event_id from bouts b").fetchall())
legs = {}
for b, bk in books.items():
    if b not in pred or b not in winner:
        continue
    r_, u_ = red[b], blue[b]
    pr = [d for d in bk.values() if r_ in d and u_ in d and 1.0 <= 1 / d[r_] + 1 / d[u_] <= 1.15]
    if len(pr) < 3:
        continue
    pr_r, pr_u = float(np.median([d[r_] for d in pr])), float(np.median([d[u_] for d in pr]))
    p = pred[b]
    er, eb = p * pr_r - 1, (1 - p) * pr_u - 1
    side_red = er >= eb
    mkt_red = (1 / pr_r) / (1 / pr_r + 1 / pr_u)
    fav_red = mkt_red >= 0.5
    legs.setdefault(ev_of[b], []).append(dict(
        edge=max(er, eb), price=pr_r if side_red else pr_u, won=(winner[b][0] == (r_ if side_red else u_)),
        fav_price=pr_r if fav_red else pr_u, fav_p=max(mkt_red, 1 - mkt_red), fav_won=(winner[b][0] == (r_ if fav_red else u_))))
print("\n== Two-fight parlays (moneyline legs, median price, one parlay per event), GBP 10 stake")
for label, key in (("model: the two highest-edge fights (edge > 0)", "model"), ("market: the two shortest-priced favourites", "fav")):
    pnl, singles, hits = [], [], 0
    for ev, ls in legs.items():
        if key == "model":
            sel = sorted([l for l in ls if l["edge"] > 0], key=lambda l: -l["edge"])[:2]
            prices, won = [l["price"] for l in sel], [l["won"] for l in sel]
        else:
            sel = sorted(ls, key=lambda l: -l["fav_p"])[:2]
            prices, won = [l["fav_price"] for l in sel], [l["fav_won"] for l in sel]
        if len(sel) < 2:
            continue
        ok = all(won)
        hits += ok
        pnl.append(STAKE * (prices[0] * prices[1] - 1) if ok else -STAKE)
        singles.append(sum(STAKE / 2 * (p - 1) if w else -STAKE / 2 for p, w in zip(prices, won)))   # same GBP 10 split into two singles
    pnl, singles = np.array(pnl), np.array(singles)
    mm = pnl[rng.integers(0, len(pnl), (3000, len(pnl)))].mean(axis=1) / STAKE
    print(f"  {label}: parlays {len(pnl)}, both won {hits} ({hits/len(pnl):.0%}), profit {pnl.sum():+,.2f}, ROI {pnl.mean()/STAKE:+.1%} [{np.percentile(mm,2.5):+.1%}, {np.percentile(mm,97.5):+.1%}]; "
          f"same legs as two 5-stake singles: profit {singles.sum():+,.2f}, ROI {singles.mean()/STAKE:+.1%}")
