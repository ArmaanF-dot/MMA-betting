"""Step 1c: the model against real sportsbook closing prices (odds_books), development period only.
predictions_ml stops at 2025-10-18, so the locked holdout is never touched. Thresholds are fixed in advance, not chosen on this data.
Prices: 'typical' = median price across books for that fighter; 'best' = best price available (line shopping)."""
import duckdb
import numpy as np

from ufcmodel.eval import metrics as M

STAKE = 10.0
c = duckdb.connect("data/processed/ufc.duckdb", read_only=True)
bf = {b: (r, u, w) for b, r, u, w in c.execute("""
  select bout_id, max(case when corner='red' then fighter_id end), max(case when corner='blue' then fighter_id end),
         max(case when result='win' and corner='red' then 1 when result='win' and corner='blue' then 0 end)
  from bout_fighter group by 1""").fetchall()}
dates = dict(c.execute("select b.bout_id, e.date from bouts b join events e using(event_id)").fetchall())
pred = {}
for b, m, p in c.execute("select bout_id, model, p_red from predictions_ml where model in ('stack','B2_lr')").fetchall():
    pred.setdefault(b, {})[m] = p
books = {}
for b, bk, f, p in c.execute("select bout_id, bookmaker, fighter_id, price_decimal from odds_books").fetchall():
    books.setdefault(b, {}).setdefault(bk, {})[f] = p

rows = []
for b, bk in books.items():
    if b not in pred or b not in bf or bf[b][2] is None or len(pred[b]) < 2:
        continue
    red, blue, w = bf[b]
    pr = [d for d in bk.values() if red in d and blue in d and 1 < d[red] < 50 and 1 < d[blue] < 50]
    pr = [d for d in pr if 1.0 <= 1 / d[red] + 1 / d[blue] <= 1.15]   # drop broken pairs
    if len(pr) < 3:
        continue
    pm = np.median([(1 / d[red]) / (1 / d[red] + 1 / d[blue]) for d in pr])
    rows.append(dict(b=b, date=str(dates[b]), w=w, mk=pm, stack=pred[b]["stack"], lr=pred[b]["B2_lr"],
                     typ=(float(np.median([d[red] for d in pr])), float(np.median([d[blue] for d in pr]))),
                     best=(max(d[red] for d in pr), max(d[blue] for d in pr))))
rows.sort(key=lambda r: r["date"])
print(f"bouts with 3+ books, a prediction and a decisive result: {len(rows)} ({rows[0]['date']} to {rows[-1]['date']})")
y = np.array([r["w"] for r in rows], float)
res = {}
for nm in ("mk", "stack", "lr"):
    p = np.array([r[nm] for r in rows])
    res[nm] = M.per_bout_log_loss(p, y)
    print(f"{nm:6s} log loss {M.log_loss(p, y):.4f}  accuracy {M.accuracy(p, y):.3f}")
print("coin   log loss 0.6931")
for nm in ("stack", "lr"):
    dm, lo, hi = M.paired_bootstrap_diff(res[nm], res["mk"])
    print(f"{nm} minus market: {dm:+.4f} [{lo:+.4f}, {hi:+.4f}]  (positive = model worse)")
# blend with the market (weight fixed at 0.5 in logit space, not tuned here)
lg = lambda p: np.log(p / (1 - p))
for nm in ("stack", "lr"):
    pb = 1 / (1 + np.exp(-(0.5 * lg(np.array([r[nm] for r in rows])) + 0.5 * lg(np.array([r["mk"] for r in rows])))))
    lb = M.per_bout_log_loss(pb, y)
    dm, lo, hi = M.paired_bootstrap_diff(lb, res["mk"])
    print(f"50/50 blend of {nm} and market minus market: {dm:+.4f} [{lo:+.4f}, {hi:+.4f}]")

rng = np.random.default_rng(0)


def bets(model, price, thr):
    out = []
    for r in rows:
        p = r[model]
        ro, bo = r[price]
        er, eb = p * ro - 1, (1 - p) * bo - 1
        if max(er, eb) > thr:
            red = er >= eb
            won = (r["w"] == 1) if red else (r["w"] == 0)
            out.append(STAKE * ((ro if red else bo) - 1) if won else -STAKE)
    return np.array(out)


def show(label, pr):
    if len(pr) == 0:
        print(f"{label:48s} no bets")
        return
    m = pr[rng.integers(0, len(pr), (4000, len(pr)))].mean(axis=1) / STAKE
    print(f"{label:48s} bets {len(pr):4d}  profit {pr.sum():+9,.2f}  ROI {pr.mean()/STAKE:+.1%} [{np.percentile(m,2.5):+.1%}, {np.percentile(m,97.5):+.1%}]")


print("\nGBP 10 flat on every fight, model's pick:")
for price in ("typ", "best"):
    for model in ("stack", "lr"):
        show(f"{model} pick at {'median' if price=='typ' else 'best'} price", bets(model, price, -9))
fav = np.array([STAKE * ((r["typ"][0] if r["mk"] > .5 else r["typ"][1]) - 1) if ((r["w"] == 1) == (r["mk"] > .5)) else -STAKE for r in rows])
show("market favourite at median price", fav)
print("\nGBP 10 flat on value bets only (edge = model p x price - 1), thresholds fixed in advance:")
for price in ("typ", "best"):
    for model in ("stack", "lr"):
        for thr in (0.0, 0.05, 0.10):
            show(f"{model}, {'median' if price=='typ' else 'best'} price, edge > {thr:.0%}", bets(model, price, thr))
