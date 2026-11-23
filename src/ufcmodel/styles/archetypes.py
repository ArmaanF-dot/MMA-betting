"""Phase 5: style axes -> soft archetype memberships -> antisymmetric style-vs-style features.

Archetypes are discovered, not named: a diagonal Gaussian mixture on the 16 as-of style axes, fit ONCE on bouts before
FIT_BEFORE so cluster labels stay stable across walk-forward folds and no test fold leaks into them. Each fighter gets soft
weights summing to 1. `sm_i_j = s_A[i] s_B[j] - s_A[j] s_B[i]` is the full antisymmetric style matrix term (a rank-free W; the
logistic model's L2 penalty is the shrinkage). Naming clusters after fighters needs Armaan's labels: see
`style_labels_template`, and `docs/decisions.md` for what is not done.
"""
import csv
import math
from pathlib import Path

import numpy as np
from sklearn.decomposition import NMF
from sklearn.metrics import adjusted_rand_score
from sklearn.mixture import GaussianMixture

from ufcmodel.features.asof import AXES, SM_COLS, SM_K

FIT_BEFORE = "2015-01-01"
CLIP = 4.0


class StyleModel:
    def __init__(self, gmm, mu, sd):
        self.gmm, self.mu, self.sd = gmm, mu, sd

    def z(self, X):
        return np.clip((np.asarray(X, float) - self.mu) / self.sd, -CLIP, CLIP)

    def weights(self, X):
        return self.gmm.predict_proba(self.z(X))


def fit_style_model(rows, k=SM_K, seed=0) -> StyleModel:
    X = np.array([r["ax_a"] for r in rows if r["date"] < FIT_BEFORE and r["stats_missing"] == 0]
                 + [r["ax_b"] for r in rows if r["date"] < FIT_BEFORE and r["stats_missing"] == 0], float)
    mu, sd = X.mean(axis=0), X.std(axis=0) + 1e-9
    Z = np.clip((X - mu) / sd, -CLIP, CLIP)
    gmm = GaussianMixture(k, covariance_type="diag", random_state=seed, n_init=3, reg_covar=1e-3).fit(Z)
    return StyleModel(gmm, mu, sd)


def sm_features(sa: np.ndarray, sb: np.ndarray) -> dict:
    return {c: float(sa[i] * sb[j] - sa[j] * sb[i]) for c, (i, j) in zip(SM_COLS, [(i, j) for i in range(SM_K) for j in range(i + 1, SM_K)])}


def add_style_matrix(rows, model: StyleModel | None = None) -> StyleModel:
    model = model or fit_style_model(rows)
    WA = model.weights([r["ax_a"] for r in rows])
    WB = model.weights([r["ax_b"] for r in rows])
    for r, a, b in zip(rows, WA, WB):
        r["arch_a"], r["arch_b"] = a, b
        r.update(sm_features(a, b))
    return model


def describe_clusters(model: StyleModel, top=3) -> list[str]:
    out = []
    for c in range(model.gmm.n_components):
        z = model.gmm.means_[c]
        order = np.argsort(-np.abs(z))[:top]
        out.append(f"Style {c} (weight {model.gmm.weights_[c]:.0%}): " + ", ".join(
            f"{'high' if z[i] > 0 else 'low'} {AXES[i]} ({z[i]:+.1f} sd)" for i in order))
    return out


def stability(rows, model: StyleModel, n_boot=20, seed=0) -> dict:
    """Bootstrap the fit on pre-FIT_BEFORE snapshots; ARI of each refit's hard labels vs the reference labels,
    plus GMM-vs-NMF agreement. 1 = identical partitions."""
    X = np.array([r["ax_a"] for r in rows if r["date"] < FIT_BEFORE and r["stats_missing"] == 0], float)
    Z = model.z(X)
    ref = model.gmm.predict(Z)
    rng = np.random.default_rng(seed)
    aris = []
    for b in range(n_boot):
        idx = rng.integers(0, len(Z), len(Z))
        g = GaussianMixture(SM_K, covariance_type="diag", random_state=b, n_init=1, reg_covar=1e-3).fit(Z[idx])
        aris.append(adjusted_rand_score(ref, g.predict(Z)))
    nn = NMF(SM_K, init="nndsvda", random_state=0, max_iter=500).fit_transform(Z - Z.min(axis=0))
    return dict(mean_ari=float(np.mean(aris)), min_ari=float(np.min(aris)), n=len(Z),
                gmm_vs_nmf_ari=float(adjusted_rand_score(ref, nn.argmax(axis=1))))


def style_labels_template(rows, names: dict, path, n=50):
    """The 50 fighters with the most bouts, with the model's current soft weights and a blank column for Armaan's own labels."""
    last = {}
    cnt = {}
    for r in rows:
        for side, w in (("a", r["arch_a"]), ("b", r["arch_b"])):
            last[r[side]] = (r["date"], w)
            cnt[r[side]] = cnt.get(r[side], 0) + 1
    top = sorted(cnt, key=cnt.get, reverse=True)[:n]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fighter", "bouts", "as_of"] + [f"model_style_{i}" for i in range(SM_K)] + ["armaan_archetype_weights (e.g. 0.6 pressure wrestler; 0.4 calf-kick attritionist)"])
        for fid in top:
            d, weights = last[fid]
            w.writerow([names.get(fid, fid), cnt[fid], d] + [round(float(x), 3) for x in weights] + [""])
