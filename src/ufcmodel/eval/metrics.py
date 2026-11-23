import numpy as np

EPS = 1e-12


def per_bout_log_loss(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def log_loss(p, y) -> float:
    return float(per_bout_log_loss(np.asarray(p, float), np.asarray(y, float)).mean())


def brier(p, y) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(((p - y) ** 2).mean())


def accuracy(p, y) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(((p > 0.5) == (y == 1)).mean())


def auc(p, y) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    n1, n0 = int((y == 1).sum()), int((y == 0).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    order = np.argsort(p, kind="mergesort")
    sp = p[order]
    ranks = np.empty(len(p))
    i = 0
    while i < len(sp):
        j = i
        while j + 1 < len(sp) and sp[j + 1] == sp[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def reliability(p, y, bins: int = 10) -> list[dict]:
    """Equal-frequency bins (deciles by default): mean prediction vs observed win rate."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    order = np.argsort(p)
    out = []
    for chunk in np.array_split(order, bins):
        if len(chunk):
            out.append(dict(mean_p=float(p[chunk].mean()), observed=float(y[chunk].mean()), n=int(len(chunk))))
    return out


def ece(p, y, bins: int = 10) -> float:
    rel = reliability(p, y, bins)
    n = sum(r["n"] for r in rel)
    return float(sum(r["n"] * abs(r["mean_p"] - r["observed"]) for r in rel) / n)


def paired_bootstrap_diff(loss_a: np.ndarray, loss_b: np.ndarray, n_boot: int = 5000, seed: int = 0):
    """Mean of (loss_a - loss_b) with a 95% percentile interval, resampling bouts. Positive = A is worse."""
    d = np.asarray(loss_a, float) - np.asarray(loss_b, float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(n_boot, len(d)))
    means = d[idx].mean(axis=1)
    return float(d.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))
