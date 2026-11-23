import numpy as np
import pytest

from ufcmodel.eval.phase4 import poisson_dev
from ufcmodel.eval.phase8 import round_label, six_label
from ufcmodel.features.asof import SM_COLS, SM_K
from ufcmodel.judging.round_score import fit_judging, p_decision_a
from ufcmodel.sim.simulator import Params, calibrate, simulate
from ufcmodel.styles.archetypes import sm_features

G = dict(sig=40.0, td=1.5, ctrl=120.0, sub=0.6, head_frac=0.65, power=0.8, chin=0.8)
W = np.array([0.8, 0.6, 0.15, 0.22, 0.1])


def fighter(**kw):
    base = dict(pace_slope=1.0, sig_for=40.0, sig_against=40.0, td_for=1.5, td_against=1.5, ctrl_for=120.0, ctrl_against=120.0,
                power=0.8, chin=0.8, sub_for=0.6, sub_against=0.6, ko_win=0.2)
    base.update(kw)
    return base


def run(fa, fb, n=20000, sched=3, **kw):
    return simulate(fa, fb, G, sched, Params(w=W, kappa=1.5, **kw), n, np.random.default_rng(0))


def test_probabilities_are_complete_and_distinct():
    o = run(fighter(), fighter())
    assert o["p_a"] + o["p_b"] + o["p_draw"] == pytest.approx(1.0, abs=1e-9)
    assert o["six"].sum() + o["p_draw"] == pytest.approx(1.0, abs=1e-9)
    assert o["round"].sum() == pytest.approx(1.0, abs=1e-9)
    assert o["round"][3:5].sum() == 0  # no rounds 4 and 5 in a three-round fight
    assert run(fighter(), fighter(), sched=5)["round"].sum() == pytest.approx(1.0)


def test_equal_fighters_are_even_and_swapping_corners_swaps_results():
    o = run(fighter(), fighter())
    assert o["p_a"] == pytest.approx(o["p_b"], abs=0.02)
    strong = fighter(sig_for=70.0, power=1.6)
    a, b = run(strong, fighter()), run(fighter(), strong)
    assert a["p_a"] > 0.6 and b["p_b"] > 0.6
    assert a["p_a"] == pytest.approx(b["p_b"], abs=0.02)


def test_better_striking_and_defence_win_more():
    base = run(fighter(), fighter())["p_a"]
    assert run(fighter(sig_for=60.0), fighter())["p_a"] > base + 0.05
    assert run(fighter(), fighter(sig_against=60.0))["p_a"] > base + 0.03   # opponent absorbs more
    assert run(fighter(td_for=4.0, ctrl_for=300.0), fighter())["p_a"] > base


def test_finish_scalars_control_finish_rates():
    low = run(fighter(), fighter(), c_ko=0.05, c_sub=0.05)["p_distance"]
    high = run(fighter(), fighter(), c_ko=0.6, c_sub=0.4)["p_distance"]
    assert high < low - 0.2


def test_calibrate_moves_finish_rates_toward_observed():
    rows = []
    for i in range(60):
        m = "KO/TKO" if i % 3 == 0 else ("Submission" if i % 6 == 1 else "Decision")
        rows.append(dict(fa=fighter(), fb=fighter(), g15=G, sched=3, method=m, end_round=1 + i % 3, sig_obs_a=60, sig_obs_b=55, fight_sec=900))
    p = calibrate(rows, Params(w=W, kappa=1.5), n=300, iters=3)
    o = simulate(fighter(), fighter(), G, 3, p, 8000, np.random.default_rng(1))
    ko = o["six"][0] + o["six"][3]
    sub = o["six"][1] + o["six"][4]
    assert ko == pytest.approx(1 / 3, abs=0.06) and sub == pytest.approx(1 / 6, abs=0.05)


def test_judging_majority_is_symmetric_and_monotone():
    X = np.array([[3.0, 0, 0, 0, 0]] * 3)
    assert p_decision_a(W, 1.5, X) > 0.95 > 0.05 > p_decision_a(W, 1.5, -X)
    assert p_decision_a(W, 1.5, X * 0) == pytest.approx(0.5)
    assert p_decision_a(W, 1.5, X) + p_decision_a(W, 1.5, -X) == pytest.approx(1.0)
    assert p_decision_a(W, 1.5, X * 0.3) < p_decision_a(W, 1.5, X)


def test_fit_judging_learns_sign_of_strikes():
    rng = np.random.default_rng(0)
    dec = []
    for i in range(400):
        x = rng.normal(0, 1, (3, 5))
        y = float(x[:, 0].sum() + rng.normal(0, 1) > 0)
        dec.append((f"b{i}", "2010-01-01", y, x))
    w, kappa, n = fit_judging(dec, "2020-01-01")
    assert n == 400 and w[0] > 0.5 and abs(w[0]) > abs(w[4])
    assert fit_judging(dec, "2000-01-01")[2] == 0   # nothing before the date: falls back to defaults


def test_style_matrix_is_antisymmetric():
    rng = np.random.default_rng(1)
    a, b = rng.dirichlet(np.ones(SM_K)), rng.dirichlet(np.ones(SM_K))
    f, g = sm_features(a, b), sm_features(b, a)
    assert set(f) == set(SM_COLS)
    assert all(f[c] == pytest.approx(-g[c]) for c in SM_COLS)
    assert all(v == pytest.approx(0) for v in sm_features(a, a).values())


def test_labels_and_deviance():
    r = dict(y=1.0, method="KO/TKO", end_round=2)
    assert six_label(r) == 0 and round_label(r) == 1
    assert six_label(dict(y=0.0, method="Submission", end_round=1)) == 4
    assert six_label(dict(y=0.5, method="Decision", end_round=3)) is None   # a draw has no winner
    assert round_label(dict(y=1.0, method="Decision", end_round=3)) == 5
    assert round_label(dict(y=1.0, method="DQ", end_round=1)) is None
    assert poisson_dev(np.array([3.0]), np.array([3.0]))[0] == pytest.approx(0)
    assert poisson_dev(np.array([0.0]), np.array([2.0]))[0] == pytest.approx(4.0)
