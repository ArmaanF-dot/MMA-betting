import numpy as np
import pytest

from ufcmodel.eval import metrics as M
from ufcmodel.eval.devig import METHODS, multiplicative, power, shin
from ufcmodel.ratings.elo import Bout, run_elo


@pytest.mark.parametrize("fn", METHODS.values())
@pytest.mark.parametrize("o", [(1.5, 2.6), (1.1, 8.0), (1.91, 1.91), (3.0, 1.45)])
def test_devig_sums_to_one(fn, o):
    p1, p2 = fn(*o)
    assert p1 + p2 == pytest.approx(1.0, abs=1e-9)
    assert (p1 > p2) == (o[0] < o[1]) or o[0] == o[1]


def test_devig_even_odds_is_half():
    for fn in METHODS.values():
        assert fn(1.91, 1.91)[0] == pytest.approx(0.5)


def test_shin_and_power_shift_margin_to_longshot_vs_multiplicative():
    o = (1.2, 5.5)  # overround > 1
    # favourite-longshot bias: Shin and power give the favourite a higher fair probability
    assert shin(*o)[0] > multiplicative(o[0], o[1])[0]
    assert power(*o)[0] > multiplicative(o[0], o[1])[0]


def _bouts(n):
    fighters = ["a", "b", "c", "d"]
    out = []
    for i in range(n):
        a, b = fighters[i % 4], fighters[(i + 1) % 4]
        out.append(Bout(f"b{i}", f"e{i // 2}", f"2020-01-{i // 2 + 1:02d}", i % 2, a, b, float(i % 3 == 0)))
    return out


def test_elo_prediction_does_not_depend_on_later_bouts():
    full = _bouts(20)
    p_full = run_elo(full, 32)
    p_cut = run_elo(full[:10], 32)
    for b in full[:10]:
        assert p_cut[b.bout_id] == p_full[b.bout_id]


def test_elo_same_event_bouts_see_pre_event_ratings():
    # fighter a fights twice in one event: both predictions use the same pre-event rating
    bouts = [Bout("x1", "e1", "2020-01-01", 0, "a", "b", 1.0), Bout("x2", "e1", "2020-01-01", 1, "a", "c", 1.0)]
    p = run_elo(bouts, 32)
    assert p["x1"] == p["x2"] == 0.5


def test_elo_no_contest_leaves_ratings_alone():
    bouts = [Bout("x1", "e1", "2020-01-01", 0, "a", "b", None), Bout("x2", "e2", "2020-02-01", 0, "a", "b", 1.0)]
    assert run_elo(bouts, 32)["x2"] == 0.5


def test_metrics_known_values():
    y, p = np.array([1, 0, 1, 0]), np.array([0.9, 0.2, 0.6, 0.6])
    assert M.accuracy(p, y) == 0.75
    assert M.auc(p, y) == pytest.approx(0.875)  # one tied pair counts half
    assert M.brier(p, y) == pytest.approx((0.1**2 + 0.2**2 + 0.4**2 + 0.6**2) / 4)
    assert M.log_loss(np.full(4, 0.5), y) == pytest.approx(np.log(2))
    assert M.auc(np.array([0.5, 0.5, 0.5, 0.5]), y) == pytest.approx(0.5)


def test_paired_bootstrap_interval_contains_mean_and_is_seeded():
    rng = np.random.default_rng(1)
    a, b = rng.normal(0.7, 0.2, 400), rng.normal(0.6, 0.2, 400)
    m, lo, hi = M.paired_bootstrap_diff(a, b)
    assert lo < m < hi and lo > 0
    assert M.paired_bootstrap_diff(a, b) == (m, lo, hi)
