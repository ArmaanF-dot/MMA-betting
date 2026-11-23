"""Walk-forward test of the four padding-related improvements, each added to the current selected model.

Development folds only (2015 to the holdout start); the locked holdout was already scored once and is not touched.
Fixed settings (window 2010, C = 0.1) so the comparison is like for like. A group is "kept" only if adding it lowers log loss
with a paired-bootstrap 95% interval entirely below zero, in either model.
"""
import numpy as np

from ufcmodel.eval import metrics as M
from ufcmodel.eval.phase10 import KEEP_GROUPS, Data, _arr, holdout_start, make_folds, walk_forward
from ufcmodel.features.asof import GROUPS, build_features, load_raw

NEW = ("acc_adjusted", "elo2", "joint_adj", "quality")


def run(con) -> str:
    raw, statics = load_raw(con)
    d = Data(build_features(raw, statics))
    folds = make_folds(holdout_start(d.rows), False)
    dev = [i for i in np.where(d.dec & (d.date >= folds[0][1]) & (d.date < folds[-1][2]))[0]]
    y = d.y[dev]
    base_groups = [g for g in KEEP_GROUPS if g in GROUPS]
    L = ["# Improvements test: stat padding and opponent quality", "",
         f"Development folds 2015 to {folds[-1][2]} ({len(dev)} decisive bouts). Current model groups: {', '.join(base_groups)}. "
         "Each improvement is added on its own, then all four together. Difference = new minus current log loss with a paired "
         "bootstrap 95% interval; negative is better.", "",
         "| Model | Added | Log loss | Difference [95% CI] | Verdict |", "|---|---|---|---|---|"]
    verdict = {}
    for kind in ("lr", "lgbm"):
        cols0 = [c for g in base_groups for c in GROUPS[g]]
        p0, _ = walk_forward(kind, cols0, d, folds, (2010, 0.1))
        l0 = M.per_bout_log_loss(_arr(d, p0, dev), y)
        L.append(f"| {kind} | (current) | {l0.mean():.4f} | | |")
        for g in NEW + ("all four",):
            extra = [c for gg in (NEW if g == "all four" else (g,)) for c in GROUPS[gg]]
            p, _ = walk_forward(kind, cols0 + extra, d, folds, (2010, 0.1))
            l1 = M.per_bout_log_loss(_arr(d, p, dev), y)
            m, lo, hi = M.paired_bootstrap_diff(l1, l0)
            ok = hi < 0
            verdict[g] = verdict.get(g, False) or ok
            L.append(f"| {kind} | {g} | {l1.mean():.4f} | {m:+.4f} [{lo:+.4f}, {hi:+.4f}] | {'helps' if ok else ('hurts' if lo > 0 else 'no clear effect')} |")
    pe = M.per_bout_log_loss(d.elo_p[dev], y)
    p2 = np.array([d.rows[i]["elo2_p"] for i in dev])
    pe2 = M.per_bout_log_loss(p2, y)
    m, lo, hi = M.paired_bootstrap_diff(pe2, pe)
    L += ["", "## Ratings on their own", "", f"Elo log loss {pe.mean():.4f}; Elo2 (margin of victory + rating deviation) {pe2.mean():.4f}; "
          f"difference {m:+.4f} [{lo:+.4f}, {hi:+.4f}].", "",
          "## Decision", ""]
    for g in NEW:
        L.append(f"- {g}: {'passes the add-on test; goes into the group selection' if verdict[g] else 'no clear gain on top of the current model'}")
    L += ["", "The final choice is made by rerunning the greedy group selection with every group available "
          "(config/feature_groups.json), so a group that only helps alongside others can still be picked.", ""]
    return "\n".join(L), verdict
