"""Remove the bookmaker margin from a two-way decimal-odds pair.

Each function takes the two decimal prices and returns the fair probabilities (they sum to 1).
"""
import math


def _implied(o1: float, o2: float) -> tuple[float, float]:
    return 1 / o1, 1 / o2


def multiplicative(o1: float, o2: float) -> tuple[float, float]:
    q1, q2 = _implied(o1, o2)
    s = q1 + q2
    return q1 / s, q2 / s


def power(o1: float, o2: float) -> tuple[float, float]:
    """p_i = q_i ** k with k chosen so the probabilities sum to 1."""
    q1, q2 = _implied(o1, o2)
    lo, hi = 0.05, 20.0
    for _ in range(100):
        k = (lo + hi) / 2
        if q1**k + q2**k > 1:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2
    return q1**k, q2**k


def shin(o1: float, o2: float) -> tuple[float, float]:
    """Shin (1993): margin comes from a share z of insider money. Falls back to multiplicative if no margin."""
    q = _implied(o1, o2)
    s = sum(q)
    if s <= 1:
        return multiplicative(o1, o2)

    def probs(z: float) -> list[float]:
        return [(math.sqrt(z * z + 4 * (1 - z) * qi * qi / s) - z) / (2 * (1 - z)) for qi in q]

    lo, hi = 0.0, 0.999
    for _ in range(100):
        z = (lo + hi) / 2
        if sum(probs(z)) > 1:
            lo = z
        else:
            hi = z
    p = probs((lo + hi) / 2)
    t = sum(p)
    return p[0] / t, p[1] / t


METHODS = {"multiplicative": multiplicative, "power": power, "shin": shin}
