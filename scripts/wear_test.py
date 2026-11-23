"""Round 8: do the wear/trend features help? Walk-forward, development folds only, current kept groups with and without
the new group. Rule fixed in advance: keep only if the paired-bootstrap interval of (with minus without) log loss is below zero
for the logistic model AND the LightGBM model does not get worse (interval upper end below +0.002)."""
import duckdb
import numpy as np

from ufcmodel.eval import metrics as M
from ufcmodel.eval.phase10 import KEPT_COLS, Data, holdout_start, make_folds, walk_forward
from ufcmodel.features.asof import GROUPS, build_features, load_raw

con = duckdb.connect("data/processed/ufc.duckdb", read_only=True)
raw, statics = load_raw(con)
d = Data(build_features(raw, statics))
folds = make_folds(holdout_start(d.rows), False)
new = GROUPS["wear_trend"]
base_cols = [c for c in KEPT_COLS if c not in new]
idx = [i for i in np.where(d.dec & (d.date >= folds[0][1]) & (d.date < folds[-1][2]))[0]]
y = d.y[idx]
L = ["# Wear and trend features (round 8)", "", f"Development folds {folds[0][1]} to {folds[-1][2]}, {len(idx)} decisive bouts. "
     "Differences: with the new group minus without (negative is better), paired bootstrap.", "",
     "| Model | Without | With | Difference [95%] |", "|---|---|---|---|"]
verdict = {}
for kind in ("lr", "lgbm"):
    p0, _ = walk_forward(kind, base_cols, d, folds)
    p1, _ = walk_forward(kind, base_cols + new, d, folds)
    a0 = np.array([p0[i] for i in idx])
    a1 = np.array([p1[i] for i in idx])
    l0, l1 = M.per_bout_log_loss(a0, y), M.per_bout_log_loss(a1, y)
    m, lo, hi = M.paired_bootstrap_diff(l1, l0)
    verdict[kind] = (m, lo, hi)
    L.append(f"| {kind} | {l0.mean():.4f} | {l1.mean():.4f} | {m:+.4f} [{lo:+.4f}, {hi:+.4f}] |")
    print(L[-1], flush=True)
keep = verdict["lr"][2] < 0 and verdict["lgbm"][2] < 0.002
L += ["", f"Keep: {'yes' if keep else 'no'}."]
open("docs/wear_trend_test.md", "w", encoding="utf-8").write("\n".join(L))
print("KEEP" if keep else "DROP", flush=True)
print("ALLDONE", flush=True)
