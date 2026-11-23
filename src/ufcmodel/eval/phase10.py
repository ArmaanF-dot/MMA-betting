"""Phases 3 (B2/B3), 9 (stack + market blend) and 10 (ablation, segments, betting simulation), on the public-data features.

Walk-forward by calendar-year fold: each fold trains only on bouts before the fold start. The training window and C are
chosen by an inner validation on the 365 days before the fold start. The locked holdout (last 12 months) is a final fold
that `run(include_holdout=True)` scores; the CLI refuses to do that twice.
"""
import json
from collections import defaultdict
from pathlib import Path
from datetime import date, timedelta

import lightgbm as lgb
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from ufcmodel.eval import metrics as M
from ufcmodel.eval.devig import shin
from ufcmodel.features.asof import ALL_COLS, GROUPS, NAMES, SYMMETRIC, build_features, load_raw
from ufcmodel.eval.phase8 import base_rates, direct_outcomes, evaluate_phase8, sim_walk_forward
from ufcmodel.judging.round_score import load_decisions
from ufcmodel.styles.archetypes import add_style_matrix

# Ablation (full model, see docs/phase10_evaluation.md history in decisions.md): only these groups had a 95% interval above
# zero in at least one model, so the models below use only them. The rest are dropped per spec principle 4.
def _load_keep():
    f = Path(__file__).resolve().parents[3] / "config" / "feature_groups.json"
    return tuple(json.load(open(f, encoding="utf-8"))["keep"]) if f.exists() else tuple(GROUPS)


KEEP_GROUPS = _load_keep()  # written by `ufcmodel select-groups`; all groups until that has been run
KEPT_COLS = [c for g in KEEP_GROUPS for c in GROUPS[g]]
WINDOWS = (2005, 2010, 2014)
C_GRID = (0.001, 0.003, 0.01, 0.03)   # strong shrinkage: with every group in, ridge beat the hard-selected set
FIRST_FOLD_YEAR = 2015
MIN_TRAIN, MIN_VAL = 300, 50
THRESHOLDS = (0.03, 0.05, 0.08)
KAPPA, BET_CAP, EVENT_CAP = 0.25, 0.02, 0.10
MIN_SEGMENT = 100
LGB_PARAMS = dict(n_estimators=250, learning_rate=0.03, num_leaves=8, min_child_samples=50, subsample=0.8,
                  subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0, random_state=0, verbose=-1, n_jobs=1)


# ---- data ----------------------------------------------------------------------------------------------------
class Data:
    def __init__(self, rows):
        self.style_model = add_style_matrix(rows)
        self.rows = rows
        self.n = len(rows)
        self.X = np.array([[r[c] for c in ALL_COLS] for r in rows], float)
        self.y = np.array([np.nan if r["y"] is None else r["y"] for r in rows], float)
        self.dec = (self.y == 0) | (self.y == 1)
        self.date = np.array([r["date"] for r in rows])
        self.year = np.array([int(r["date"][:4]) for r in rows])
        self.bid = [r["bout_id"] for r in rows]
        self.elo_p = np.array([r["elo_p"] for r in rows])
        self.a_n = np.array([r["a_n"] for r in rows])
        self.b_n = np.array([r["b_n"] for r in rows])
        self.odds_a = np.array([np.nan if r["odds_a"] is None else r["odds_a"] for r in rows], float)
        self.odds_b = np.array([np.nan if r["odds_b"] is None else r["odds_b"] for r in rows], float)
        self.has_odds = np.isfinite(self.odds_a) & np.isfinite(self.odds_b)
        self.p_mkt = np.full(self.n, np.nan)
        for i in np.where(self.has_odds)[0]:
            self.p_mkt[i] = shin(self.odds_a[i], self.odds_b[i])[0]
        self.event = [r["event_id"] for r in rows]

    def mask(self, start, end):
        return (self.date >= start) & (self.date < end)


def holdout_start(rows) -> str:
    last = date.fromisoformat(max(r["date"] for r in rows))
    return (last - timedelta(days=365) + timedelta(days=1)).isoformat()


def make_folds(hold: str, include_holdout: bool):
    folds = []
    for y in range(FIRST_FOLD_YEAR, int(hold[:4]) + 1):
        start = f"{y}-01-01"
        end = hold if y == int(hold[:4]) else f"{y + 1}-01-01"
        if start < end:
            folds.append((str(y), start, end))
    if include_holdout:
        folds.append(("holdout", hold, "9999-12-31"))
    return folds


# ---- models --------------------------------------------------------------------------------------------------
MONO = {"d_elo": 1, "d_wr_decay": 1, "d_wr_all": 1, "d_sig_for": 1, "d_sig_against": -1, "d_sig_def": 1, "d_sig_acc": 1,
        "d_td_for": 1, "d_td_against": -1, "d_td_def": 1, "d_td_acc": 1, "d_power": 1, "d_chin": -1, "d_ko_loss": -1,
        "d_sub_loss": -1, "d_ctrl_for": 1, "d_ctrl_against": -1, "td_matchup": 1, "str_matchup": 1, "ctrl_matchup": 1}


class Model:
    """Symmetric: trained on both corner orders, predicts P(A) as the average of both."""

    def __init__(self, kind, cols, C=0.1):
        self.mono = kind == "lgbm_mono"
        self.kind, self.cols, self.C = ("lgbm" if kind.startswith("lgbm") else kind), cols, C
        self.ci = [ALL_COLS.index(c) for c in cols]
        self.anti = np.array([c not in SYMMETRIC for c in cols])

    def _flip(self, X):
        Z = X.copy()
        Z[:, self.anti] *= -1
        return Z

    def _in(self, X):
        return self.scaler.transform(np.nan_to_num(X, nan=0.0)) if self.kind == "lr" else X

    def fit(self, Xfull, y):
        X = Xfull[:, self.ci]
        X2, y2 = np.vstack([X, self._flip(X)]), np.concatenate([y, 1 - y])
        if self.kind == "lr":
            self.scaler = StandardScaler(with_mean=False).fit(np.nan_to_num(X2, nan=0.0))
            self.m = LogisticRegression(C=self.C, fit_intercept=False, max_iter=2000).fit(self._in(X2), y2)
        else:
            extra = dict(monotone_constraints=[MONO.get(c, 0) for c in self.cols]) if self.mono else {}
            self.m = lgb.LGBMClassifier(**LGB_PARAMS, **extra).fit(X2, y2)
        return self

    def predict(self, Xfull):
        X = Xfull[:, self.ci]
        return 0.5 * (self.m.predict_proba(self._in(X))[:, 1] + 1 - self.m.predict_proba(self._in(self._flip(X)))[:, 1])

    def contributions(self, Xfull):
        """LR only: per-feature log-odds contribution for each row (antisymmetric by construction)."""
        X = self._in(Xfull[:, self.ci])
        return X * self.m.coef_[0]


def _ll(p, y):
    return M.log_loss(p, y)


def select_params(kind, cols, d: Data, fold_start):
    val_start = (date.fromisoformat(fold_start) - timedelta(days=365)).isoformat()
    best, best_ll = (2005, 0.1), np.inf
    for start_year in WINDOWS:
        tr = d.dec & (d.year >= start_year) & (d.date < val_start)
        va = d.dec & (d.date >= val_start) & (d.date < fold_start)
        if tr.sum() < MIN_TRAIN or va.sum() < MIN_VAL:
            continue
        for C in (C_GRID if kind == "lr" else (0.1,)):
            ll = _ll(Model(kind, cols, C).fit(d.X[tr], d.y[tr]).predict(d.X[va]), d.y[va])
            if ll < best_ll:
                best, best_ll = (start_year, C), ll
    return best


def walk_forward(kind, cols, d: Data, folds, fixed=None):
    preds, chosen = {}, {}
    for name, start, end in folds:
        start_year, C = fixed or select_params(kind, cols, d, start)
        chosen[name] = (start_year, C)
        tr = d.dec & (d.year >= start_year) & (d.date < start)
        te = d.mask(start, end)
        if not te.any():
            continue
        p = Model(kind, cols, C).fit(d.X[tr], d.y[tr]).predict(d.X[te])
        for i, pi in zip(np.where(te)[0], p):
            preds[i] = pi
    return preds, chosen


def _logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def stack_and_blend(d: Data, comp: dict, folds):
    """comp: {name: {row index: p}}. Fold i is stacked on folds before it; the first two folds only train."""
    ens, blend, ws = {}, {}, {}
    names = list(comp)
    for fi in range(2, len(folds)):
        name, start, end = folds[fi]
        prior = d.dec & (d.date < start) & (d.date >= folds[0][1])
        te = d.mask(start, end)
        idx_tr = [i for i in np.where(prior)[0] if all(i in comp[n] for n in names)]
        idx_te = [i for i in np.where(te)[0] if all(i in comp[n] for n in names)]
        if not idx_tr or not idx_te:
            continue
        Z = lambda idx: np.array([[_logit(comp[n][i]) for n in names] for i in idx])
        st = LogisticRegression(C=1.0, fit_intercept=False, max_iter=1000).fit(
            np.vstack([Z(idx_tr), -Z(idx_tr)]), np.concatenate([d.y[idx_tr], 1 - d.y[idx_tr]]))
        pe = st.predict_proba(Z(idx_te))[:, 1]
        for i, p in zip(idx_te, pe):
            ens[i] = p
        # blend weight on earlier folds that have odds
        ib = [i for i in idx_tr if d.has_odds[i]]
        pe_tr = st.predict_proba(Z(ib))[:, 1]
        best_w, best_ll = 1.0, np.inf
        for w in np.linspace(0, 1, 11):
            pb = 1 / (1 + np.exp(-(w * _logit(pe_tr) + (1 - w) * _logit(d.p_mkt[ib]))))
            ll = _ll(pb, d.y[ib])
            if ll < best_ll:
                best_w, best_ll = w, ll
        ws[name] = (float(best_w), {n: round(float(c), 3) for n, c in zip(names, st.coef_[0])})
        for i in idx_te:
            blend[i] = 1 / (1 + np.exp(-(best_w * _logit(ens[i]) + (1 - best_w) * _logit(d.p_mkt[i])))) if d.has_odds[i] else ens[i]
    return ens, blend, ws


# ---- betting simulation --------------------------------------------------------------------------------------
def place_bets(d: Data, p, idx, thr):
    bets = []
    for i in idx:
        if not d.has_odds[i] or i not in p or not d.dec[i]:
            continue
        ea, eb = p[i] * d.odds_a[i] - 1, (1 - p[i]) * d.odds_b[i] - 1
        t = thr if min(d.a_n[i], d.b_n[i]) >= 3 else 2 * thr  # low-coverage bouts need a bigger edge
        side, edge = ("A", ea) if ea >= eb else ("B", eb)
        if edge > t:
            o = d.odds_a[i] if side == "A" else d.odds_b[i]
            pw = p[i] if side == "A" else 1 - p[i]
            won = (d.y[i] == 1) if side == "A" else (d.y[i] == 0)
            bets.append(dict(i=i, event=d.event[i], date=d.date[i], side=side, odds=float(o), p=float(pw), edge=float(edge), won=bool(won)))
    return bets


def simulate_betting(d: Data, p, folds, seed=0):
    allbets, thr_by_fold = [], {}
    for fi in range(3, len(folds)):
        name, start, end = folds[fi]
        prior_idx = [i for i in np.where(d.dec & (d.date < start))[0] if i in p]
        best_thr, best_roi = 0.05, -np.inf
        for thr in THRESHOLDS:
            b = place_bets(d, p, prior_idx, thr)
            if len(b) >= 100:
                roi = sum((x["odds"] - 1) if x["won"] else -1 for x in b) / len(b)
                if roi > best_roi:
                    best_thr, best_roi = thr, roi
        thr_by_fold[name] = best_thr
        allbets += place_bets(d, p, np.where(d.mask(start, end))[0], best_thr)
    if not allbets:
        return dict(n=0), []
    profit = np.array([(b["odds"] - 1) if b["won"] else -1.0 for b in allbets])
    rng = np.random.default_rng(seed)
    boots = profit[rng.integers(0, len(profit), (2000, len(profit)))].mean(axis=1)
    bank, peak, mdd, by_event = 1.0, 1.0, 0.0, defaultdict(list)
    for b in sorted(allbets, key=lambda x: (x["date"], x["event"])):
        by_event[(b["date"], b["event"])].append(b)
    for _, bs in sorted(by_event.items()):
        fr = [min(BET_CAP, KAPPA * (b["p"] * b["odds"] - 1) / (b["odds"] - 1)) for b in bs]
        scale = min(1.0, EVENT_CAP / sum(fr)) if sum(fr) > 0 else 0
        start_bank = bank
        for b, f in zip(bs, fr):
            bank += start_bank * f * scale * ((b["odds"] - 1) if b["won"] else -1)
        peak = max(peak, bank)
        mdd = max(mdd, (peak - bank) / peak)
    return dict(n=len(allbets), hit=float(np.mean([b["won"] for b in allbets])), roi=float(profit.mean()),
                lo=float(np.percentile(boots, 2.5)), hi=float(np.percentile(boots, 97.5)), final_bank=float(bank),
                max_drawdown=float(mdd), thresholds=thr_by_fold), allbets


# ---- pipeline ------------------------------------------------------------------------------------------------
def run_pipeline(con, include_holdout=False):
    raw, statics = load_raw(con)
    rows = build_features(raw, statics)
    d = Data(rows)
    hold = holdout_start(rows)
    folds = make_folds(hold, include_holdout)
    comp, chosen = {}, {}
    comp["lr"], chosen["lr"] = walk_forward("lr", KEPT_COLS, d, folds)
    comp["lgbm"], chosen["lgbm"] = walk_forward("lgbm", KEPT_COLS, d, folds)
    comp_m, chosen_m = walk_forward("lgbm_mono", KEPT_COLS, d, folds)
    dev_rows = [i for i in comp["lgbm"] if d.dec[i] and d.date[i] < hold]
    ll_u, ll_m = _ll(_arr(d, comp["lgbm"], dev_rows), d.y[dev_rows]), _ll(_arr(d, comp_m, dev_rows), d.y[dev_rows])
    mono_choice = (ll_u, ll_m, "monotone" if ll_m < ll_u else "unconstrained")
    if ll_m < ll_u:
        comp["lgbm"], chosen["lgbm"] = comp_m, chosen_m
    comp["elo"] = {i: d.elo_p[i] for i in range(d.n) if d.date[i] >= folds[0][1]}
    sim = sim_walk_forward(d, folds, load_decisions(con))
    comp["sim"] = {i: v["p"] for i, v in sim.items() if isinstance(i, (int, np.integer))}
    ens, blend, ws = stack_and_blend(d, comp, folds)
    return dict(d=d, folds=folds, hold=hold, comp=comp, chosen=chosen, ens=ens, blend=blend, ws=ws, sim=sim, mono_choice=mono_choice)


def phase8_text(res, folds_eval, idx_eval):
    d = res["d"]
    six, rnd = direct_outcomes(d, folds_eval)
    bsix, brnd = base_rates(d, folds_eval)
    return evaluate_phase8(d, res["sim"], six, rnd, bsix, brnd, res["comp"], idx_eval)


def _fmt(t):
    return f"{t[0]:+.4f} [{t[1]:+.4f}, {t[2]:+.4f}]"


def _arr(d, p, idx):
    return np.array([p[i] for i in idx])


def ablation(d: Data, folds):
    dev_idx = [i for i in np.where(d.dec & (d.date >= folds[0][1]) & (d.date < folds[-1][2]))[0]]
    out = {}
    for kind, base_cols in (("lr", ALL_COLS), ("lgbm", ALL_COLS)):
        fixed = (2010, 0.1)
        full, _ = walk_forward(kind, base_cols, d, folds, fixed)
        full_loss = M.per_bout_log_loss(_arr(d, full, dev_idx), d.y[dev_idx])
        for g, gcols in GROUPS.items():
            cols = [c for c in base_cols if c not in gcols]
            pr, _ = walk_forward(kind, cols, d, folds, fixed)
            loss = M.per_bout_log_loss(_arr(d, pr, dev_idx), d.y[dev_idx])
            out[(kind, g)] = (len(dev_idx), float(full_loss.mean()), float(loss.mean()), M.paired_bootstrap_diff(loss, full_loss))
    return out


def calibration_check(d: Data, ens, folds):
    """Walk-forward: fit a calibrator on earlier folds' stack outputs, score the next fold. Raw vs Platt vs beta vs isotonic."""
    from sklearn.isotonic import IsotonicRegression
    res = defaultdict(list)
    ys = []
    for fi in range(3, len(folds)):
        _, start, end = folds[fi]
        if folds[fi][0] == "holdout":
            continue
        tr = [i for i in ens if d.dec[i] and d.date[i] < start]
        te = [i for i in ens if d.dec[i] and start <= d.date[i] < end]
        if len(tr) < 300 or not te:
            continue
        ptr, ytr, pte = _arr(d, ens, tr), d.y[tr], _arr(d, ens, te)
        ys.append(d.y[te])
        res["none"].append(pte)
        lt = lambda p: _logit(p).reshape(-1, 1)
        res["platt"].append(LogisticRegression(C=1e4).fit(np.vstack([lt(ptr), -lt(ptr)]), np.concatenate([ytr, 1 - ytr])).predict_proba(lt(pte))[:, 1])
        bf = lambda p: np.column_stack([np.log(np.clip(p, 1e-6, 1)), -np.log(np.clip(1 - p, 1e-6, 1))])
        res["beta"].append(LogisticRegression(C=1e4).fit(bf(ptr), ytr).predict_proba(bf(pte))[:, 1])
        res["isotonic"].append(np.clip(IsotonicRegression(out_of_bounds="clip").fit(ptr, ytr).predict(pte), 0.02, 0.98))
    y = np.concatenate(ys)
    L = ["## Calibration of the stack (fit on earlier folds, scored on the next)", "", "| Calibrator | Log loss | ECE |", "|---|---|---|"]
    for k, v in res.items():
        p = np.concatenate(v)
        L.append(f"| {k} | {M.log_loss(p, y):.4f} | {M.ece(p, y):.3f} |")
    return L + [""]


def member_spread(d: Data, comp, idx):
    return np.array([np.std([_logit(comp[n][i]) for n in comp]) for i in idx])


def disagreement_model(d: Data, comp, ens, folds):
    """Does the model's historic edge over the market depend on coverage, debut status, odds range and how much the ensemble
    members disagree? Target: the stack beat the market on that bout. Walk-forward logistic; AUC with a bootstrap interval."""
    idx = [i for i in ens if d.dec[i] and d.has_odds[i] and d.date[i] < folds[-1][2]]
    if len(idx) < 600:
        return ["## Disagreement model", "", "Not enough bouts with odds.", ""]
    ll_m = M.per_bout_log_loss(d.p_mkt[idx], d.y[idx])
    ll_e = M.per_bout_log_loss(_arr(d, ens, idx), d.y[idx])
    target = (ll_e < ll_m).astype(float)
    spread = member_spread(d, comp, idx)
    gap = np.abs(_logit(_arr(d, ens, idx)) - _logit(d.p_mkt[idx]))
    X = np.column_stack([np.minimum(d.a_n[idx], d.b_n[idx]), [d.rows[i]["any_debut"] for i in idx], spread, gap, d.p_mkt[idx],
                         [d.rows[i]["is_women"] for i in idx], [d.rows[i]["main_event"] for i in idx]])
    dates = d.date[idx]
    preds = np.full(len(idx), np.nan)
    for _, start, end in folds:
        tr = (dates < start) & (dates >= folds[2][1])
        te = (dates >= start) & (dates < end)
        if tr.sum() < 300 or not te.any():
            continue
        sc = StandardScaler().fit(X[tr])
        preds[te] = LogisticRegression(C=0.3, max_iter=1000).fit(sc.transform(X[tr]), target[tr]).predict_proba(sc.transform(X[te]))[:, 1]
    ok = ~np.isnan(preds)
    rng = np.random.default_rng(0)
    aucs = []
    for _ in range(500):
        b = rng.integers(0, ok.sum(), ok.sum())
        aucs.append(M.auc(preds[ok][b], target[ok][b]))
    auc = M.auc(preds[ok], target[ok])
    q = np.quantile(preds[ok], 0.8)
    top = ok & (preds >= q)
    L = ["## Disagreement model (when has the stack beaten the market?)", "",
         f"Target: stack log loss below the market's on that bout (base rate {target[ok].mean():.1%}). Features: fewer bouts of the two fighters, "
         "debut flag, spread (sd of component log-odds), size of the model-market gap, market probability, sex, main event. "
         f"Walk-forward AUC on {ok.sum()} bouts: {auc:.3f} (bootstrap 95% [{np.percentile(aucs, 2.5):.3f}, {np.percentile(aucs, 97.5):.3f}]).", "",
         f"- Top quintile by predicted chance: stack minus market log loss {np.mean(ll_e[top] - ll_m[top]):+.4f}; the rest: {np.mean(ll_e[ok & ~top] - ll_m[ok & ~top]):+.4f} "
         "(negative = stack better).",
         "- Reading: an AUC interval that includes 0.5 means no usable signal about when the model beats the market.", ""]
    return L


def evaluate(res, with_ablation=True):
    d, folds, comp, ens, blend = res["d"], res["folds"], res["comp"], res["ens"], res["blend"]
    L = ["# Evaluation: B2/B3, stack, market blend, ablation, betting simulation (public-data features)", ""]
    L += ["Generated by `python -m ufcmodel phase10`. Walk-forward by calendar year; locked holdout is not scored in this report.", ""]
    L += ["## Read this first", "",
          "- The odds are one scraped pair per bout with no opening/closing label or timestamp. The spec forbids using closing "
          "prices at decision time, and these may be close to closing, so the **blend and the betting simulation are optimistic "
          "and are not evidence of a real edge**. Closing-line value cannot be measured here.",
          "- Features cover results history, age, physicals, activity and fight-level totals only. No per-round, positional or "
          "tagged data, so skills (Phase 4), styles (5), simulator and judging (8) are not built.",
          "- Elo K is fixed at 64; recency half-life fixed at 24 months (not tuned, see decisions.md).",
          f"- B2 and B3 use only the feature groups the first ablation kept: {', '.join(KEEP_GROUPS)}. The ablation table below is "
          "the full-model ablation that decided this, rerun here; the pruning was chosen on these same folds, so treat the pruned "
          "numbers as slightly optimistic until the one-time holdout confirms them.", ""]
    chosen = res["chosen"]
    L += ["## Chosen training window and C per fold (inner validation on the previous year)", "",
          "| Fold | LR window / C | LightGBM window |", "|---|---|---|"]
    for name, *_ in folds:
        if name in chosen["lr"]:
            L.append(f"| {name} | {chosen['lr'][name][0]} / {chosen['lr'][name][1]} | {chosen['lgbm'][name][0]} |")
    L.append("")

    first_stack = folds[2][1]
    dev_end = [f for f in folds if f[0] != "holdout"][-1][2]
    idx_all = [i for i in np.where(d.dec & (d.date >= folds[0][1]) & (d.date < dev_end))[0] if i in comp["lr"] and i in comp["lgbm"]]
    y = d.y[idx_all]
    L += ["## B1/B2/B3 on every decisive bout 2015 to the holdout", "",
          "| Model | n | Log loss | Brier | Accuracy | AUC | ECE |", "|---|---|---|---|---|---|---|"]
    for nm, p in (("Coin flip", {i: 0.5 for i in idx_all}), ("B1 Elo (as-of, K=64)", comp["elo"]), ("B2 logistic", comp["lr"]), ("B3 LightGBM", comp["lgbm"])):
        pa = _arr(d, p, idx_all)
        L.append(f"| {nm} | {len(idx_all)} | {M.log_loss(pa, y):.4f} | {M.brier(pa, y):.4f} | {M.accuracy(pa, y):.3f} | {M.auc(pa, y):.3f} | {M.ece(pa, y):.3f} |")
    ll_b = {nm: M.per_bout_log_loss(_arr(d, p, idx_all), y) for nm, p in (("elo", comp["elo"]), ("lr", comp["lr"]), ("lgbm", comp["lgbm"]))}
    L += ["", "Paired bootstrap, log-loss difference (positive = first is worse):", ""]
    for a, b in (("lr", "elo"), ("lgbm", "elo"), ("lgbm", "lr")):
        L.append(f"- {a} minus {b}: {_fmt(M.paired_bootstrap_diff(ll_b[a], ll_b[b]))}")
    L.append("")

    common = [i for i in np.where(d.dec & d.has_odds & (d.date >= first_stack) & (d.date < dev_end))[0] if i in blend]
    yc = d.y[common]
    models = {"Coin flip": {i: 0.5 for i in common}, "B0 market (Shin)": {i: d.p_mkt[i] for i in common},
              "B1 Elo": comp["elo"], "B2 logistic": comp["lr"], "B3 LightGBM": comp["lgbm"], "M4 simulator": comp["sim"],
              "Stack (no market)": ens, "Blend with market": blend}
    L += [f"## Common set: decisive bouts with odds, {first_stack[:4]} to the holdout (n = {len(common)})", "",
          "| Model | Log loss | Brier | Accuracy | AUC | ECE |", "|---|---|---|---|---|---|"]
    lossc = {}
    for nm, p in models.items():
        pa = _arr(d, p, common)
        lossc[nm] = M.per_bout_log_loss(pa, yc)
        L.append(f"| {nm} | {M.log_loss(pa, yc):.4f} | {M.brier(pa, yc):.4f} | {M.accuracy(pa, yc):.3f} | {M.auc(pa, yc):.3f} | {M.ece(pa, yc):.3f} |")
    L += ["", "Log-loss gap, paired bootstrap 95% interval (positive = first is worse):", "", "| Comparison | Mean difference [95% CI] |", "|---|---|"]
    for a, b in (("Stack (no market)", "B0 market (Shin)"), ("Blend with market", "B0 market (Shin)"), ("M4 simulator", "B0 market (Shin)"), ("Stack (no market)", "B3 LightGBM"),
                 ("Stack (no market)", "B2 logistic"), ("B3 LightGBM", "B0 market (Shin)"), ("B2 logistic", "B0 market (Shin)")):
        L.append(f"| {a} minus {b} | {_fmt(M.paired_bootstrap_diff(lossc[a], lossc[b]))} |")
    L += ["", "Blend weights on the model (1 = model only) and stack coefficients per fold:", ""]
    for name, (w, coefs) in res["ws"].items():
        L.append(f"- {name}: w = {w:.1f}, stack = {coefs}")
    L.append("")

    L += ["## Reliability, blend vs market (deciles)", "", "| Decile | Market p | Observed | Blend p | Observed |", "|---|---|---|---|---|"]
    rm, rb = M.reliability(_arr(d, models["B0 market (Shin)"], common), yc), M.reliability(_arr(d, blend, common), yc)
    for k, (a, b) in enumerate(zip(rm, rb), 1):
        L.append(f"| {k} | {a['mean_p']:.3f} | {a['observed']:.3f} | {b['mean_p']:.3f} | {b['observed']:.3f} |")
    L.append("")

    def seg(title, keyfn):
        g = defaultdict(list)
        for k, i in enumerate(common):
            g[keyfn(i)].append(k)
        rows = [f"## {title}", "", "| Segment | n | Market LL | Blend LL | Blend minus market [95% CI] | Stack minus market [95% CI] |", "|---|---|---|---|---|---|"]
        for key, ks in sorted(g.items(), key=lambda kv: str(kv[0])):
            if len(ks) < MIN_SEGMENT:
                continue
            ks = np.array(ks)
            mk, bl, sk = lossc["B0 market (Shin)"][ks], lossc["Blend with market"][ks], lossc["Stack (no market)"][ks]
            rows.append(f"| {key} | {len(ks)} | {mk.mean():.4f} | {bl.mean():.4f} | {_fmt(M.paired_bootstrap_diff(bl, mk))} | {_fmt(M.paired_bootstrap_diff(sk, mk))} |")
        return rows + [""]

    L += seg("By year", lambda i: str(d.year[i]))
    L += seg("By sex", lambda i: "Women" if d.rows[i]["is_women"] else "Men")
    L += seg("By debutant (either fighter has no earlier bout in the data)", lambda i: "Debutant" if d.rows[i]["any_debut"] else "Experienced")
    L += seg("By division", lambda i: d.rows[i]["wc"])
    L += ["Not available: main card vs prelims, five vs three rounds, tagged vs untagged.", ""]

    L += [f"## Monotone constraints (LightGBM where the direction is known)", "",
          f"Dev-fold log loss: unconstrained {res['mono_choice'][0]:.4f}, monotone {res['mono_choice'][1]:.4f}; used: {res['mono_choice'][2]}.", ""]
    L += calibration_check(d, ens, [f for f in folds])
    L += disagreement_model(d, comp, ens, [f for f in folds if f[0] != "holdout"])
    bet, bets = simulate_betting(d, blend, folds)
    L += ["## Betting simulation (blend; flat 1 unit and 0.25-Kelly, 2% per-bet and 10% per-event caps)", "",
          "Threshold per fold is picked from 3/5/8% on earlier folds' flat ROI; bouts with a fighter under 3 bouts need double. "
          "**Uses the stand-in odds, so treat as an upper bound, not a forecast.**", ""]
    if bet["n"]:
        L += [f"- Bets: {bet['n']}, hit rate {bet['hit']:.1%}", f"- Flat ROI: {bet['roi']:+.1%} per unit staked, 95% bootstrap [{bet['lo']:+.1%}, {bet['hi']:+.1%}]",
              f"- 0.25-Kelly: bankroll 1.00 to {bet['final_bank']:.2f}, max drawdown {bet['max_drawdown']:.0%}",
              f"- Thresholds by fold: {bet['thresholds']}", "- Closing-line value: not measurable (no timestamps or closing prices)."]
    else:
        L.append("- No bets cleared the threshold.")
    L.append("")
    L += ["## Paper-trading gate (Phase 11)", "",
          "**Not passed and cannot be started:** it needs live recommendations on future events with real decision-time and closing "
          "prices (at least 8 events or 100 recommendations) and a positive closing-line value interval. The dataset ends "
          "2023-09-16. `ufcmodel.betting.paper` has the log and grading code ready.", ""]

    if with_ablation:
        ab = ablation(d, [f for f in folds if f[0] != "holdout"])
        L += ["## Ablation: remove one feature group (fixed window 2010, C = 0.1; all decisive bouts 2015 to the holdout)", "",
              "Positive = removing the group made it worse, so the group helps. Many comparisons: treat small gains with suspicion.", "",
              "| Model | Group removed | n | Full LL | Without LL | Difference [95% CI] | Keep? |", "|---|---|---|---|---|---|---|"]
        for (kind, g), (n, full, wo, ci) in ab.items():
            keep = "keep" if ci[1] > 0 else ("drop candidate" if ci[2] < 0 or abs(ci[0]) < 0.0005 else "inconclusive")
            L.append(f"| {'LR (all cols)' if kind == 'lr' else 'LightGBM'} | {g} | {n} | {full:.4f} | {wo:.4f} | {_fmt(ci)} | {keep} |")
        L.append("")
    return "\n".join(L), bet


def explain(model: Model, d: Data, i: int, top=5):
    """Top drivers of a bout from the logistic model, as plain-text lines."""
    c = model.contributions(d.X[i:i + 1])[0]
    order = np.argsort(-np.abs(c))[:top]
    return [(NAMES.get(model.cols[k], model.cols[k]), float(c[k])) for k in order]


def run(con, report_path=None, with_ablation=True):
    res = run_pipeline(con, include_holdout=False)
    text, bet = evaluate(res, with_ablation)
    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(text)
    d = res["d"]
    dev = [f for f in res["folds"] if f[0] != "holdout"]
    dev_idx = [i for i in range(d.n) if d.date[i] >= dev[0][1] and d.date[i] < dev[-1][2]]
    with open(str(report_path).replace("phase10_evaluation", "phase8_simulator"), "w", encoding="utf-8") as f:
        f.write(phase8_text(res, dev, dev_idx))
    con.execute("CREATE OR REPLACE TABLE predictions_ml (bout_id VARCHAR, model VARCHAR, p_red DOUBLE, snapshot_date DATE)")
    out = []
    for name, p in (("B2_lr", res["comp"]["lr"]), ("B3_lgbm", res["comp"]["lgbm"]), ("stack", res["ens"]), ("blend", res["blend"])):
        out += [(d.bid[i], name, float(v), d.date[i]) for i, v in p.items()]
    con.executemany("INSERT INTO predictions_ml VALUES (?, ?, ?, ?)", out)
    json.dump({k: {n: list(v) for n, v in vv.items()} for k, vv in res["chosen"].items()},
              open("data/processed/chosen_params.json", "w"))
    json.dump({n: [w, coefs] for n, (w, coefs) in res["ws"].items()}, open("data/processed/stack.json", "w"))
    return text


def holdout_report(con, path):
    """Score the locked holdout once. Everything is frozen: same pipeline, holdout appended as the last fold.
    The odds file ends in 2023, so a recent holdout has no market to compare with: model-only metrics are reported."""
    res = run_pipeline(con, include_holdout=True)
    d, folds = res["d"], res["folds"]
    name, start, end = folds[-1]
    hold_idx = [int(i) for i in np.where(d.mask(start, end))[0]]
    idx = [i for i in hold_idx if d.dec[i] and i in res["blend"]]
    idx_o = [i for i in idx if d.has_odds[i]]
    L = [f"# Locked holdout, scored once ({start} to the end of the data)", "",
         f"Bouts: {len(hold_idx)}; decisive: {len(idx)}; with odds: {len(idx_o)}. Reported as is. "
         f"Stack and blend were fit only on earlier folds (blend weight w = {res['ws'][name][0]:.1f}).", "",
         "| Model | n | Log loss | Brier | Accuracy | AUC | ECE |", "|---|---|---|---|---|---|---|"]
    models = [("Coin flip", {i: 0.5 for i in idx}, idx), ("B1 Elo", res["comp"]["elo"], idx), ("B2 logistic", res["comp"]["lr"], idx),
              ("B3 LightGBM", res["comp"]["lgbm"], idx), ("M4 simulator", res["comp"]["sim"], idx), ("Stack (no market)", res["ens"], idx)]
    if len(idx_o) >= 50:
        models += [("B0 market (Shin)", {i: d.p_mkt[i] for i in idx_o}, idx_o), ("Blend with market", res["blend"], idx_o)]
    losses = {}
    for nm, p, ix in models:
        pa, yy = _arr(d, p, ix), d.y[ix]
        losses[nm] = M.per_bout_log_loss(pa, yy)
        L.append(f"| {nm} | {len(ix)} | {M.log_loss(pa, yy):.4f} | {M.brier(pa, yy):.4f} | {M.accuracy(pa, yy):.3f} | {M.auc(pa, yy):.3f} | {M.ece(pa, yy):.3f} |")
    L += ["", "Paired bootstrap on the decisive holdout bouts (positive = first is worse):", ""]
    for a, b in (("Stack (no market)", "B1 Elo"), ("Stack (no market)", "Coin flip"), ("B3 LightGBM", "B2 logistic"), ("M4 simulator", "B3 LightGBM")):
        L.append(f"- {a} minus {b}: {_fmt(M.paired_bootstrap_diff(losses[a], losses[b]))}")
    if len(idx_o) < 50:
        L += ["", "No market comparison: the odds file ends 2023-09-16, so there are no de-vigged odds for this holdout."]
    six, rnd = direct_outcomes(d, [folds[-1]])
    bsix, brnd = base_rates(d, [folds[-1]])
    L += ["", evaluate_phase8(d, res["sim"], six, rnd, bsix, brnd, res["comp"], hold_idx)]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return "\n".join(L)


def select_groups(con, path):
    """Greedy forward selection of feature groups with the walk-forward logistic model (fixed window 2010, C = 0.1).
    A group is added only if the best remaining one lowers log loss with a paired-bootstrap 95% interval below zero.
    Single-group ablation misleads when groups overlap (Elo and record carry the same results history), so this decides."""
    raw, statics = load_raw(con)
    d = Data(build_features(raw, statics))
    hold = holdout_start(d.rows)
    folds = [f for f in make_folds(hold, False)]
    dev = [i for i in np.where(d.dec & (d.date >= folds[0][1]) & (d.date < folds[-1][2]))[0]]
    y = d.y[dev]
    cur = np.full(len(dev), np.log(2))
    chosen, log, remaining = [], [], list(GROUPS)
    while remaining:
        best = None
        for g in remaining:
            cols = [c for gg in chosen + [g] for c in GROUPS[gg]]
            pr, _ = walk_forward("lr", cols, d, folds, (2010, 0.1))
            loss = M.per_bout_log_loss(_arr(d, pr, dev), y)
            diff = M.paired_bootstrap_diff(loss, cur)
            if best is None or diff[0] < best[1][0]:
                best = (g, diff, loss)
        log.append((best[0], float(best[2].mean()), best[1], best[1][2] < 0))
        if best[1][2] < 0:
            chosen.append(best[0])
            cur = best[2]
            remaining.remove(best[0])
        else:
            break
    json.dump({"keep": chosen, "log": [[g, ll, list(ci), bool(ok)] for g, ll, ci, ok in log], "model": "lr, window 2010, C 0.1"},
              open(path, "w", encoding="utf-8"), indent=1)
    return chosen, log
