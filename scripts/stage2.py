"""Stage 2 of docs/profit_plan.md, rules as pre-registered there. Development period only (to 2025-10-24); the betting holdout
(2025-10-25 to 2026-10-24) is not used.
  2.1 the model against the market of record, 2015 to 2025
  H2  favourite-longshot bias: logistic slope of the result on logit(market fair probability), at the open and at the close;
      discovery 2015-2021, validation 2022-2025; kept only if the slope differs from 1 with the interval excluding 1 in both, same direction
  H1  line shopping against the leave-one-out consensus (per-book data, 2023-06 on): flat 10 on the best price of a side when
      price x the other books' median fair probability - 1 exceeds 2% or 4%; all books, UK-reachable books only (BetWay, Unibet),
      and an exchange version (consensus fair price less 1% spread, 2% or 5% commission on winnings: an assumption);
      kept only if the validation return interval is above zero for a fixed threshold"""
from collections import defaultdict
from statistics import median

import duckdb
import numpy as np
from sklearn.linear_model import LogisticRegression

from ufcmodel.eval.betting_eval import MarketOfRecord, clv, devig, flat_returns, loss_gap

END, STAKE = "2025-10-24", 10.0
con = duckdb.connect("data/processed/ufc.duckdb", read_only=True)
mk = MarketOfRecord()
ev = {b: (e, str(d)) for b, e, d in con.execute("SELECT b.bout_id, b.event_id, e.date FROM bouts b JOIN events e USING (event_id)").fetchall()}
win = {b: c for b, c in con.execute("SELECT bout_id, corner FROM bout_fighter WHERE result = 'win'").fetchall()}
preds = defaultdict(dict)
for b, m, p in con.execute("SELECT bout_id, model, p_red FROM predictions_ml WHERE model IN ('stack', 'B2_lr')").fetchall():
    preds[b][m] = p
rows = []
for b, (e, d) in ev.items():
    if b not in win or not "2015-01-01" <= d <= END:
        continue
    pc, src = mk.close(b)
    if pc is None:
        continue
    rows.append(dict(b=b, e=e, d=d, y=float(win[b] == "red"), pc=pc, src=src, po=mk.open(b), lr=preds[b].get("B2_lr"), stack=preds[b].get("stack")))
rows.sort(key=lambda r: r["d"])
print(f"{len(rows)} decisive bouts with a closing price, 2015-01-01 to {END}; sources: " + ", ".join(f"{s} {sum(r['src'] == s for r in rows)}" for s in ("books", "range", "old")), flush=True)
out = ["# Stage 2 results (development period only)", ""]


def say(s=""):
    print(s, flush=True)
    out.append(s)


# ---- 2.1 --------------------------------------------------------------------------------------------------------------------
say("## 2.1 The model against the market of record")
say("")
say("| Period | Model | Bouts | Model log loss | Market log loss | Model minus market [95%] |")
say("|---|---|---|---|---|---|")
for label, lo, hi in (("2015-2021", "2015", "2021"), ("2022-2025", "2022", "2025"), ("2015-2025", "2015", "2025")):
    for m in ("lr", "stack"):
        rs = [r for r in rows if r[m] is not None and lo <= r["d"][:4] <= hi]
        if len(rs) < 100:
            continue
        g = loss_gap([r[m] for r in rs], [r["pc"] for r in rs], [r["y"] for r in rs])
        say(f"| {label} | {m} | {len(rs)} | {g['model']:.4f} | {g['market']:.4f} | {g['gap'][0]:+.4f} [{g['gap'][1]:+.4f}, {g['gap'][2]:+.4f}] |")
say("")
say("By source of the closing price (logistic model, 2015-2025):")
say("")
for s in ("old", "range", "books"):
    rs = [r for r in rows if r["src"] == s and r["lr"] is not None]
    if len(rs) >= 100:
        g = loss_gap([r["lr"] for r in rs], [r["pc"] for r in rs], [r["y"] for r in rs])
        say(f"- {s}: {len(rs)} bouts, model minus market {g['gap'][0]:+.4f} [{g['gap'][1]:+.4f}, {g['gap'][2]:+.4f}]")
say("")

# ---- H2 ---------------------------------------------------------------------------------------------------------------------
lg = lambda p: np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))
rng = np.random.default_rng(0)


def slope(rs, key):
    x = lg(np.array([r[key] for r in rs]))
    y = np.array([r["y"] for r in rs])
    X = np.concatenate([x, -x])[:, None]
    Y = np.concatenate([y, 1 - y])
    return float(LogisticRegression(C=np.inf, fit_intercept=False, max_iter=500).fit(X, Y).coef_[0, 0])


def slope_ci(rs, key, n_boot=400):
    by = defaultdict(list)
    for r in rs:
        by[r["e"]].append(r)
    groups = list(by.values())
    s = [slope([r for i in rng.integers(0, len(groups), len(groups)) for r in groups[i]], key) for _ in range(n_boot)]
    return slope(rs, key), np.percentile(s, 2.5), np.percentile(s, 97.5)


say("## H2 Favourite-longshot bias: slope of result on logit(market fair probability); above 1 means favourites are underpriced")
say("")
say("| Price | Period | Bouts | Slope [95%] |")
say("|---|---|---|---|")
res_h2 = {}
for key, name in (("pc", "close"), ("po", "open")):
    for label, lo, hi in (("discovery 2015-2021", "2015", "2021"), ("validation 2022-2025", "2022", "2025")):
        rs = [r for r in rows if r[key] is not None and lo <= r["d"][:4] <= hi]
        s, a, b = slope_ci(rs, key)
        res_h2[(name, label[:3])] = (s, a, b)
        say(f"| {name} | {label} | {len(rs)} | {s:.3f} [{a:.3f}, {b:.3f}] |")
say("")
kept = []
for name in ("close", "open"):
    d_, v_ = res_h2[(name, "dis")], res_h2[(name, "val")]
    ok = (d_[1] > 1 and v_[1] > 1) or (d_[2] < 1 and v_[2] < 1)
    kept.append(ok)
    say(f"- {name}: kept = {ok} (discovery [{d_[1]:.3f}, {d_[2]:.3f}], validation [{v_[1]:.3f}, {v_[2]:.3f}], needs both intervals on the same side of 1)")
say("")

# ---- H1 ---------------------------------------------------------------------------------------------------------------------
say("## H1 Line shopping against the leave-one-out consensus (per-book data, 2023-06 to 2025-10-24)")
say("")
UK = {"BetWay", "Unibet"}
fights = []
for b, (e, d) in ev.items():
    if b not in win or not "2023-06-01" <= d <= END:
        continue
    r_, u_ = mk.red[b], mk.blue[b]
    per = {bk: x for bk, x in mk.books.get(b, {}).items() if r_ in x and u_ in x and 1 < x[r_] < 50 and 1 < x[u_] < 50 and 1.0 <= 1 / x[r_] + 1 / x[u_] <= 1.15}
    if len(per) < 4:
        continue
    fights.append(dict(e=e, red_won=win[b] == "red", per={bk: (x[r_], x[u_]) for bk, x in per.items()}))
say(f"{len(fights)} fights with 4+ books (so each leave-one-out consensus has 3+).")
say("")
say("| Venue | Threshold | Bets | Profit | Return [95%, events as units] | Mean closing-line value |")
say("|---|---|---|---|---|---|")
h1 = {}
for venue in ("all books", "UK-reachable books", "exchange 2% commission", "exchange 5% commission"):
    for thr in (0.02, 0.04):
        prof, evs, clvs = [], [], []
        for f in fights:
            fair_all = median(devig(a, c) for a, c in f["per"].values())
            best = None
            for side in (0, 1):
                for bk, pr in f["per"].items():
                    if venue == "UK-reachable books" and bk not in UK:
                        continue
                    others = [devig(a, c) if side == 0 else devig(c, a) for k2, (a, c) in f["per"].items() if k2 != bk]
                    pc = median(others)
                    price = pr[side]
                    edge = price * pc - 1
                    if edge > thr and (best is None or edge > best[0]):
                        best = (edge, side, price, pc, bk)
            if best is None:
                continue
            _, side, price, pc, bk = best
            won = f["red_won"] if side == 0 else not f["red_won"]
            fair_side = fair_all if side == 0 else 1 - fair_all
            if venue.startswith("exchange"):
                comm = 0.02 if "2%" in venue else 0.05
                px = 1 / fair_side - 0.01 * (1 / fair_side)       # fair price less 1% spread: assumption
                prof.append(STAKE * (px - 1) * (1 - comm) if won else -STAKE)
                clvs.append(clv(px, fair_side))
            else:
                prof.append(STAKE * (price - 1) if won else -STAKE)
                clvs.append(clv(price, fair_side))
            evs.append(f["e"])
        r = flat_returns(prof, evs, stake=STAKE)
        h1[(venue, thr)] = r
        if r["n"]:
            say(f"| {venue} | {thr:.0%} | {r['n']} | {r['profit']:+,.0f} | {r['roi']:+.1%} [{r['lo']:+.1%}, {r['hi']:+.1%}] | {np.mean(clvs):+.3f} |")
        else:
            say(f"| {venue} | {thr:.0%} | 0 | | | |")
say("")
ok1 = any(r["n"] and r["lo"] > 0 for (v, t), r in h1.items() if not v.startswith("exchange"))
say(f"H1 kept (sportsbook venues, validation interval above zero for a fixed threshold): {ok1}.")
say("The exchange rows price the same selected sides at the consensus fair price (an assumption): they show what the costs alone do, not a tradable price.")
open("docs/stage2_results.md", "w", encoding="utf-8").write("\n".join(out))
print("ALLDONE", flush=True)

