from datetime import date

import numpy as np
import pytest

from ufcmodel.features.asof import RawBout
from ufcmodel.features.joint import add_joint_features
from ufcmodel.ratings.elo2 import RD0, RD_MIN, Elo2, expected, margin


def test_elo2_expected_is_symmetric_and_uncertainty_pulls_to_half():
    assert expected(1600, 1500, 80, 80) + expected(1500, 1600, 80, 80) == pytest.approx(1.0)
    assert 0.5 < expected(1600, 1500, 200, 200) < expected(1600, 1500, 60, 60)


def test_elo2_margin_and_rating_deviation():
    assert margin(1.0, "KO", 30, 10, 1.0) > margin(1.0, "DEC", 30, 28, 1.0) > 1.0
    assert margin(0.5, "DEC", 30, 10, 1.0) == 1.0
    el = Elo2(48, 1.0, 40, 0.9)
    d = date(2020, 1, 1)
    assert el.state("a", d) == (1500.0, RD0)
    el.update_event([("a", "b", 1.0, "KO", 40, 10)], d)
    ra, rda = el.state("a", d)
    rb, _ = el.state("b", d)
    assert ra > 1500 > rb and ra - 1500 == pytest.approx(1500 - rb)
    assert rda == pytest.approx(RD0 * 0.9)
    assert el.state("a", date(2023, 1, 1))[1] > rda          # time out widens uncertainty
    for k in range(60):
        el.update_event([("a", f"x{k}", 1.0, "DEC", 20, 19)], d)
    assert el.state("a", d)[1] == pytest.approx(RD_MIN)


def _bout(i, d, a, b, sa, sb):
    st = lambda x: dict(sig_l=x, td_l=1, ctrl_sec=60)
    return RawBout(f"b{i}", f"e{i}", d, 0, "Lightweight", a, b, 1.0, "Decision", 3, 300, st(sa), st(sb), fight_sec=900)


def test_joint_fit_separates_offence_from_opposition_and_uses_only_earlier_months():
    rng = np.random.default_rng(0)
    fighters = [f"f{i}" for i in range(12)]
    raw = []
    for i in range(700):
        d = f"{2010 + i // 120}-{(i // 10) % 12 + 1:02d}-15"
        a, b = rng.choice(fighters, 2, replace=False)
        # f0 lands far more than anyone; f1 concedes far more than anyone
        lam_a = 30 * (2.0 if a == "f0" else 1.0) * (2.0 if b == "f1" else 1.0)
        lam_b = 30 * (2.0 if b == "f0" else 1.0) * (2.0 if a == "f1" else 1.0)
        raw.append(_bout(i, d, a, b, rng.poisson(lam_a), rng.poisson(lam_b)))
    rows = [dict(a=b.a, b=b.b, date=b.date) for b in raw]
    add_joint_features(rows, raw)
    late = [r for r in rows if r["date"] >= "2014-01-01"]
    off = [r["j_sig_l_off"] for r in late if r["a"] == "f0" and r["b"] != "f1"]
    dfn = [r["j_sig_l_def"] for r in late if r["a"] == "f1" and r["b"] != "f0"]
    assert np.mean(off) > 0.4          # f0's offence is recovered (true log ratio 0.69)
    assert np.mean(dfn) < -0.4         # f1's defence is worse
    # a bout's features do not change when everything from its own month onwards is deleted
    target = rows[500]
    cut_raw = [b for b in raw if b.date[:7] < target["date"][:7]] + [raw[500]]
    cut_rows = [dict(a=b.a, b=b.b, date=b.date) for b in cut_raw]
    add_joint_features(cut_rows, cut_raw)
    assert cut_rows[-1]["j_sig_l_off"] == pytest.approx(target["j_sig_l_off"])
