"""Stage 3 of docs/profit_plan.md, rules as pre-registered there. Development period only (to 2025-10-24); discovery 2015-2021,
validation 2022-2025. The model probability is the market-free walk-forward logistic model (predictions_ml B2_lr).

  H3  does the model predict how the line moves from open to close?  delta = logit(close) - logit(open) on
      x = logit(model) - logit(open), through the origin, standard errors clustered by event.  Kept if the coefficient on x is above
      zero with the interval excluding zero in discovery AND validation.  Close here is the midpoint of the closing range on the
      fighter pages and open the opening pair, so both come from one source.
  H4  logistic model with logit(market close) as a fixed offset plus 11 features, ridge penalty chosen on a time split inside
      discovery (fit 2015-2018, score 2019-2021), fit on discovery, scored on validation.  Kept if validation log loss beats the
      market with the paired interval below zero.
        1 age difference  2 aged 35+  3 layoff of a year or more  4 last fight lost by KO/TKO  5 KO/TKO losses in the last 3
        6 padding index (decayed raw strike differential per 15 min minus the opponent-adjusted one)  7 win streak of 3+
        8 debut  9 short notice  10 reach difference  11 model gap = logit(model) - logit(market)
      Deviation, flagged: #9 is 'late-created matchup' x logit(market), since the flag says the fight was late, not which fighter
      was the replacement, and a symmetric flag cannot enter a difference between fighters.
  H5  residual momentum: a fighter's past sum of (result - market probability), shrunk by fight count (sum / (n + 5)), A minus B;
      tested alone (offset model, coefficient interval, discovery and validation) and as a 12th feature of H4.
All features use only fights before the bout. Holm correction across H3-H5 would apply only to survivors."""
import math
from collections import defaultdict

import duckdb
import numpy as np
from scipy.optimize import minimize

from ufcmodel.eval import metrics as M
from ufcmodel.eval.betting_eval import MarketOfRecord, devig, flat_returns
from ufcmodel.eval.phase10 import Data
from ufcmodel.features.asof import HALF_LIFE_MONTHS, build_features, load_raw

END = "2025-10-24"
con = duckdb.connect("data/processed/ufc.duckdb", read_only=True)
mk = MarketOfRecord()
raw, statics = load_raw(con)
rows = build_features(raw, statics)
Data(rows)                      # adds the style-matrix columns the rows need
by_bout = {r["bout_id"]: r for r in rows}
pred_lr = dict(con.execute("SELECT bout_id, p_red FROM predictions_ml WHERE model = 'B2_lr'").fetchall())
ev_of = dict(con.execute("SELECT bout_id, event_id FROM bouts").fetchall())
oc = duckdb.connect("data/processed/odds_oc.duckdb", read_only=True)
mu = {b: m for b, m in oc.execute("SELECT bout_id, mu FROM odds_open_close WHERE mu IS NOT NULL").fetchall()}
ev_mu = defaultdict(list)
for b, m in mu.items():
    ev_mu[ev_of[b]].append(m)
ev_med = {e: float(np.median(v)) for e, v in ev_mu.items() if len(v) >= 5}
lg = lambda p: np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))

# ---- as-of fighter histories for the raw features (one chronological pass, event by event) -----------------------------------
hist = defaultdict(list)    # fighter -> [dict(date, score, cat, sf, sa, minutes, resid)]
feat = {}                   # bout_id -> dict of per-fighter raw features for red ('a') and blue ('b')
ordered = sorted(raw, key=lambda b: (b.date, b.event_id, b.order))
k_shrink = 5.0
half = HALF_LIFE_MONTHS


def fighter_raw(fid, d_iso, adj_diff):
    h = hist[fid]
    from datetime import date as _d
    dd = _d.fromisoformat(d_iso)
    last3 = h[-3:]
    ko3 = float(sum(1 for r in last3 if r["cat"] == "KO" and r["score"] == 0.0))
    streak = float(len(last3) == 3 and all(r["score"] == 1.0 for r in last3))
    num = den = 0.0
    for r in h:
        if r["sf"] is None or r["sa"] is None or not r["minutes"]:
            continue
        w = 0.5 ** ((dd - r["date"]).days / 30.44 / half)
        num += w * (r["sf"] - r["sa"])
        den += w * r["minutes"]
    raw_diff = 15.0 * num / den if den > 0 else float("nan")
    padding = raw_diff - adj_diff if not math.isnan(raw_diff) else 0.0
    res = [r["resid"] for r in h if r["resid"] is not None]
    mom = sum(res) / (len(res) + k_shrink)
    return dict(ko3=ko3, streak=streak, padding=padding, mom=mom)


i = 0
while i < len(ordered):
    j = i
    while j < len(ordered) and (ordered[j].date, ordered[j].event_id) == (ordered[i].date, ordered[i].event_id):
        j += 1
    event = ordered[i:j]
    for b in event:
        r = by_bout.get(b.bout_id)
        if r is None:
            continue
        fa, fb = r["fa"], r["fb"]
        feat[b.bout_id] = (fighter_raw(b.a, b.date, fa["sig_for"] - fa["sig_against"]), fighter_raw(b.b, b.date, fb["sig_for"] - fb["sig_against"]))
    from datetime import date as _dd
    for b in event:
        if b.score_a is None:
            continue
        pc, _ = mk.close(b.bout_id)
        cat = {"KO/TKO": "KO", "Submission": "SUB", "Decision": "DEC"}.get(b.method, "OTHER")
        mins = b.fight_sec / 60 if b.fight_sec else None
        for me, sc, st, ot, p_me in ((b.a, b.score_a, b.stats_a, b.stats_b, pc), (b.b, 1 - b.score_a, b.stats_b, b.stats_a, None if pc is None else 1 - pc)):
            hist[me].append(dict(date=_dd.fromisoformat(b.date), score=sc, cat=cat if sc != 0.5 else "OTHER", sf=st.get("sig_l"), sa=ot.get("sig_l"),
                                 minutes=mins, resid=None if p_me is None or sc == 0.5 else sc - p_me))
    i = j

# ---- dataset ----------------------------------------------------------------------------------------------------------------
data = []
for r in rows:
    b, d = r["bout_id"], r["date"]
    if r["y"] not in (0.0, 1.0) or not "2015-01-01" <= d <= END or b not in pred_lr or b not in feat:
        continue
    pc, src = mk.close(b)
    if pc is None:
        continue
    o = mk.oc.get(b)
    po = mk.open(b)
    pc_oc = devig((o["low_red"] + o["high_red"]) / 2, (o["low_blue"] + o["high_blue"]) / 2) if o and all(o[k] for k in ("low_red", "high_red", "low_blue", "high_blue")) else None
    fa, fb = r["fa"], r["fb"]
    ra, rb = feat[b]
    ind = lambda f, k, t: float(f[k] > t) if not math.isnan(f[k]) else 0.0
    zf = lambda x: 0.0 if x is None or (isinstance(x, float) and math.isnan(x)) else x
    late = float(b in mu and ev_of[b] in ev_med and mu[b] - ev_med[ev_of[b]] > 150)
    x_model = float(lg(pred_lr[b]) - lg(pc))
    data.append(dict(
        b=b, e=ev_of[b], d=d, y=r["y"], pc=pc, po=po, pc_oc=pc_oc, model=pred_lr[b],
        f=[zf(r["d_age"]), ind(fa, "age", 35) - ind(fb, "age", 35), ind(fa, "days_since", 365) - ind(fb, "days_since", 365), zf(r["d_after_ko_loss"]),
           ra["ko3"] - rb["ko3"], ra["padding"] - rb["padding"], ra["streak"] - rb["streak"], zf(r["d_debut"]), late * float(lg(pc)),
           zf(r["d_reach"]), x_model],
        mom=ra["mom"] - rb["mom"], red_price=(o or {}).get("open_red"), blue_price=(o or {}).get("open_blue"), elo=r["elo_p"]))
NAMES = ["age diff", "aged 35+", "layoff 1y+", "last fight KO loss", "KO losses in last 3", "padding index", "win streak 3+", "debut",
         "late matchup x market", "reach diff", "model gap"]
disc = [x for x in data if x["d"] < "2022-01-01"]
val = [x for x in data if x["d"] >= "2022-01-01"]
out = ["# Stage 3 results (development period only)", ""]


def say(s=""):
    print(s, flush=True)
    out.append(s)


say(f"{len(data)} decisive bouts with a closing price and a model prediction: discovery {len(disc)}, validation {len(val)}.")
say("")


# ---- cluster-robust OLS through the origin --------------------------------------------------------------------------------
def ols(X, y, groups):
    X, y = np.asarray(X, float), np.asarray(y, float)
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta
    meat = np.zeros((X.shape[1], X.shape[1]))
    idx = defaultdict(list)
    for k, g in enumerate(groups):
        idx[g].append(k)
    for ks in idx.values():
        s = X[ks].T @ resid[ks]
        meat += np.outer(s, s)
    cov = XtX_inv @ meat @ XtX_inv
    return beta, np.sqrt(np.diag(cov))


# ---- H3 -------------------------------------------------------------------------------------------------------------------
say("## H3 Does the model predict the opening-to-closing move?")
say("")
say("| Period | Bouts | Coefficient on x = logit(model) - logit(open) [95%] | R^2 of the move |")
say("|---|---|---|---|")
h3 = {}
for label, ds in (("discovery 2015-2021", disc), ("validation 2022-2025", val)):
    rs = [x for x in ds if x["po"] is not None and x["pc_oc"] is not None]
    xx = np.array([lg(x["model"]) - lg(x["po"]) for x in rs])
    dd = np.array([lg(x["pc_oc"]) - lg(x["po"]) for x in rs])
    beta, se = ols(xx[:, None], dd, [x["e"] for x in rs])
    r2 = 1 - np.sum((dd - beta[0] * xx) ** 2) / np.sum(dd ** 2)
    h3[label[:3]] = (beta[0], beta[0] - 1.96 * se[0], beta[0] + 1.96 * se[0])
    say(f"| {label} | {len(rs)} | {beta[0]:+.4f} [{beta[0] - 1.96 * se[0]:+.4f}, {beta[0] + 1.96 * se[0]:+.4f}] | {r2:.4f} |")
say("")
ok3 = all(v[1] > 0 for v in h3.values())
say(f"H3 kept (coefficient above zero with the interval excluding zero in both periods): {ok3}.")
say("")
say("Which of the H4 features predict the move (all bouts 2015-2025, standardised coefficients on the closing move, clustered by event)?")
say("")
rs = [x for x in data if x["po"] is not None and x["pc_oc"] is not None]
F = np.array([x["f"] for x in rs])
F_s = F / F.std(axis=0)
dd = np.array([lg(x["pc_oc"]) - lg(x["po"]) for x in rs])
beta, se = ols(F_s, dd, [x["e"] for x in rs])
say("| Feature | Coefficient (per 1 sd) [95%] |")
say("|---|---|")
for n, bb, s in zip(NAMES, beta, se):
    say(f"| {n} | {bb:+.4f} [{bb - 1.96 * s:+.4f}, {bb + 1.96 * s:+.4f}] |")
say("")
if ok3:
    say("Strategy rows (only because H3 was kept): predicted move toward a side above 0.05 logit, bet at the opening price.")
    b3 = h3["dis"][0] * 0 + np.mean([h3["dis"][0], h3["val"][0]])
    for label, ds in (("validation 2022-2025", val),):
        prof, evs, clvs = [], [], []
        for x in ds:
            if x["po"] is None or x["pc_oc"] is None or not x["red_price"] or not x["blue_price"]:
                continue
            mv = b3 * (lg(x["model"]) - lg(x["po"]))
            if abs(mv) <= 0.05:
                continue
            red = mv > 0
            price = x["red_price"] if red else x["blue_price"]
            won = (x["y"] == 1.0) == red
            fair_close = x["pc_oc"] if red else 1 - x["pc_oc"]
            prof.append(10 * (price - 1) if won else -10.0)
            evs.append(x["e"])
            clvs.append(math.log(price * fair_close))
        r = flat_returns(prof, evs, stake=10.0)
        say(f"- {label}: {r['n']} bets, return {r['roi']:+.1%} [{r['lo']:+.1%}, {r['hi']:+.1%}], mean closing-line value {np.mean(clvs):+.4f}")
    say("")


# ---- offset logistic with ridge ------------------------------------------------------------------------------------------
def fit_offset(F, off, y, lam):
    def nll(b):
        z = off + F @ b
        return np.sum(np.logaddexp(0, z) - y * z) + lam * np.sum(b ** 2)

    def grad(b):
        z = off + F @ b
        return F.T @ (1 / (1 + np.exp(-z)) - y) + 2 * lam * b
    return minimize(nll, np.zeros(F.shape[1]), jac=grad, method="L-BFGS-B").x


def prep(ds, cols):
    F = np.array([[x["f"][c] if c < 11 else x["mom"] for c in cols] for x in ds], float)
    return F, np.array([lg(x["pc"]) for x in ds]), np.array([x["y"] for x in ds])


def run_h4(cols, label):
    Fd, od, yd = prep(disc, cols)
    mean, sd = Fd.mean(axis=0), Fd.std(axis=0)
    sd[sd == 0] = 1
    Fs = lambda F: (F - mean) / sd
    early = [i for i, x in enumerate(disc) if x["d"] < "2019-01-01"]
    late_ = [i for i, x in enumerate(disc) if x["d"] >= "2019-01-01"]
    best, best_ll = None, 1e9
    for lam in (1.0, 10.0, 30.0, 100.0, 300.0, 1000.0):
        b = fit_offset(Fs(Fd)[early], od[early], yd[early], lam)
        z = od[late_] + Fs(Fd)[late_] @ b
        ll = float(np.mean(np.logaddexp(0, z) - yd[late_] * z))
        if ll < best_ll:
            best, best_ll = lam, ll
    b = fit_offset(Fs(Fd), od, yd, best)
    Fv, ov, yv = prep(val, cols)
    pv = 1 / (1 + np.exp(-(ov + Fs(Fv) @ b)))
    pm = np.array([x["pc"] for x in val])
    l_m, l_k = M.per_bout_log_loss(pv, yv), M.per_bout_log_loss(pm, yv)
    gap = M.paired_bootstrap_diff(l_m, l_k)
    say(f"{label}: ridge lambda {best:g}; validation log loss {l_m.mean():.4f} vs market {l_k.mean():.4f}; model minus market {gap[0]:+.4f} [{gap[1]:+.4f}, {gap[2]:+.4f}] ({len(val)} bouts)")
    return b, gap, pv, best, mean, sd


say("## H4 Market-residual model (offset = logit of the closing market probability)")
say("")
b11, gap11, pv11, lam11, mean11, sd11 = run_h4(list(range(11)), "11 features")
say("")
say("| Feature | Coefficient on the log-odds, per 1 sd (discovery fit) |")
say("|---|---|")
for n, bb in zip(NAMES, b11):
    say(f"| {n} | {bb:+.4f} |")
say("")
ok4 = gap11[2] < 0
say(f"H4 kept (validation log loss beats the market, interval below zero): {ok4}.")
say("")
say("Same model without the 'model gap' feature (is the model adding anything, or only the other 10?):")
run_h4(list(range(10)), "10 features, no model gap")
say("")

# ---- H5 -------------------------------------------------------------------------------------------------------------------
say("## H5 Residual momentum (past sum of result minus market probability, shrunk by fight count)")
say("")
say("| Period | Bouts | Coefficient on logit scale, per 1 sd [95%, events bootstrap] |")
say("|---|---|---|")
rng = np.random.default_rng(0)
h5 = {}
for label, ds in (("discovery 2015-2021", disc), ("validation 2022-2025", val)):
    m = np.array([x["mom"] for x in ds])
    sd_m = m.std()
    F = (m / sd_m)[:, None]
    off = np.array([lg(x["pc"]) for x in ds])
    y = np.array([x["y"] for x in ds])
    b0 = fit_offset(F, off, y, 1.0)[0]
    groups = defaultdict(list)
    for k, x in enumerate(ds):
        groups[x["e"]].append(k)
    gl = list(groups.values())
    bs = []
    for _ in range(300):
        ix = [k for g in rng.integers(0, len(gl), len(gl)) for k in gl[g]]
        bs.append(fit_offset(F[ix], off[ix], y[ix], 1.0)[0])
    h5[label[:3]] = (b0, np.percentile(bs, 2.5), np.percentile(bs, 97.5))
    say(f"| {label} | {len(ds)} | {b0:+.4f} [{h5[label[:3]][1]:+.4f}, {h5[label[:3]][2]:+.4f}] |")
say("")
ok5 = all(v[1] > 0 for v in h5.values()) or all(v[2] < 0 for v in h5.values())
say(f"H5 kept (interval excludes zero in both periods, same sign): {ok5}.")
say("")
say("As a 12th feature of H4:")
run_h4(list(range(11)) + [11], "12 features")
say("")
say(f"Survivors: H3 {ok3}, H4 {ok4}, H5 {ok5}.")
import pickle
pickle.dump(dict(data=data, b11=b11, mean11=mean11, sd11=sd11, names=NAMES), open("data/processed/stage3.pkl", "wb"))
open("docs/stage3_results.md", "w", encoding="utf-8").write("\n".join(out))
print("ALLDONE", flush=True)
