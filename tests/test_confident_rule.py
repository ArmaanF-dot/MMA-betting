from ufcmodel.reports.livecard import CONF_COLS, confident_row

CARD = dict(best_a=1.30, best_a_book="BetWay", best_b=3.9, best_b_book="Unibet", odds_a=1.27, odds_b=3.6)


def result(p_model, p_mkt=0.72):
    return dict(p_model=p_model, p_mkt=p_mkt, b=dict(date="2026-11-14", fighter_a="A Fighter", fighter_b="B Fighter"))


def test_logs_a_pick_at_or_above_70_and_flags_80():
    row = confident_row(result(0.83), CARD, "ev", "thu", "2026-11-12T12:00:00Z")
    assert len(row) == len(CONF_COLS)
    d = dict(zip(CONF_COLS, row))
    assert d["pick"] == "A Fighter" and d["opponent"] == "B Fighter" and d["tier"] == "80+" and d["model_p_pick"] == 0.83
    assert d["best_price"] == 1.30 and d["best_book"] == "BetWay" and d["median_price"] == 1.27 and d["slot"] == "thu" and d["rule"] == "C3_v1"
    assert dict(zip(CONF_COLS, confident_row(result(0.74), CARD, "ev", "mon", "t")))["tier"] == "70-80"


def test_picks_the_other_corner_with_its_own_price_and_market_probability():
    d = dict(zip(CONF_COLS, confident_row(result(0.15, p_mkt=0.30), CARD, "ev", "pre", "t")))
    assert d["pick"] == "B Fighter" and d["opponent"] == "A Fighter" and d["tier"] == "80+" and d["model_p_pick"] == 0.85
    assert d["best_price"] == 3.9 and d["best_book"] == "Unibet" and d["median_price"] == 3.6 and d["market_p_pick"] == 0.70


def test_nothing_below_70_and_edges_of_the_cutoffs():
    assert confident_row(result(0.69), CARD, "ev", "mon", "t") is None
    assert confident_row(result(0.31), CARD, "ev", "mon", "t") is None
    assert confident_row(result(0.70), CARD, "ev", "mon", "t") is not None
    assert dict(zip(CONF_COLS, confident_row(result(0.80), CARD, "ev", "mon", "t")))["tier"] == "80+"
    assert dict(zip(CONF_COLS, confident_row(result(0.70, p_mkt=None), CARD, "ev", "mon", "t")))["market_p_pick"] == ""
