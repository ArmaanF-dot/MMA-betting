import math

import duckdb
import numpy as np
import pytest

from ufcmodel.eval import betting_eval as B
from ufcmodel.ingest.bfo import american_to_decimal
from ufcmodel.ingest.bfo_fighters import _matchup_id, parse_fighter


def test_devig_and_clv():
    assert B.devig(2.0, 2.0) == pytest.approx(0.5)
    assert B.devig(1.5, 3.0) == pytest.approx((1 / 1.5) / (1 / 1.5 + 1 / 3.0))
    assert B.devig(1.8, 2.1) + B.devig(2.1, 1.8) == pytest.approx(1.0)
    assert B.clv(2.2, 0.5) == pytest.approx(math.log(1.1))      # a price better than fair is above zero
    assert B.clv(1.8, 0.5) < 0


def test_flat_returns_clusters_by_event():
    profits = [10, -10, 10, -10, 10, 10]
    events = ["a", "a", "b", "b", "c", "c"]
    r = B.flat_returns(profits, events, stake=10.0)
    assert r["n"] == 6 and r["profit"] == 20 and r["roi"] == pytest.approx(1 / 3)
    assert r["lo"] <= r["roi"] <= r["hi"]
    assert B.flat_returns([], [])["roi"] is None
    assert B.flat_profit(2.5, True) == 15 and B.flat_profit(2.5, False) == -10


def test_loss_gap_sign():
    y = np.array([1, 0, 1, 1, 0, 0, 1, 0] * 20, float)
    market = np.where(y == 1, 0.7, 0.3)
    model = np.full(len(y), 0.5)
    g = B.loss_gap(model, market, y)
    assert g["model"] > g["market"] and g["gap"][0] > 0   # the uninformative model is worse than the informed market


def test_american_prices():
    assert american_to_decimal("+150") == pytest.approx(2.5)
    assert american_to_decimal("-200") == pytest.approx(1.5)
    assert american_to_decimal("n/a") is None


def test_fighter_page_row_parsing():
    html = """<table class="team-stats-table"><tr><th>Matchup</th></tr>
      <tr class="event-header"><td><a href="/events/x-1">UFC 1</a> Oct 24th 2026</td></tr>
      <tr class="main-row"><th><a>A Fighter</a></th><td><span>-120</span></td><td><span>-112</span></td><td>...</td><td><span>+110</span></td>
        <td class="chart-cell" data-li="[4452,1]" data-sparkline="1.8, 1.9"></td></tr>
      <tr><th><a>B Fighter</a></th><td><span>-110</span></td><td><span>-120</span></td><td>...</td><td><span>-104</span></td></tr></table>"""
    r = parse_fighter(html)[0]
    assert (r["fighter"], r["opponent"], r["event"]) == ("A Fighter", "B Fighter", "UFC 1") and str(r["date"]) == "2026-10-24"
    assert r["open_a"] == pytest.approx(1 + 100 / 120) and r["high_a"] == pytest.approx(2.1) and r["mu"] == 4452
    assert _matchup_id(None) is None


def test_market_of_record_prefers_books_then_range_then_old(tmp_path):
    main, oc = str(tmp_path / "m.duckdb"), str(tmp_path / "oc.duckdb")
    c = duckdb.connect(main)
    c.execute("CREATE TABLE bout_fighter (bout_id VARCHAR, fighter_id VARCHAR, corner VARCHAR, result VARCHAR)")
    c.execute("CREATE TABLE odds_snapshots (bout_id VARCHAR, bookmaker VARCHAR, ts TIMESTAMP, fighter_id VARCHAR, price_decimal DOUBLE, kind VARCHAR)")
    c.execute("CREATE TABLE odds_books (bout_id VARCHAR, bookmaker VARCHAR, fighter_id VARCHAR, price_decimal DOUBLE, kind VARCHAR, source VARCHAR, fetched_at TIMESTAMP)")
    for b in ("b1", "b2", "b3", "b4"):
        c.execute("INSERT INTO bout_fighter VALUES (?, ?, 'red', NULL), (?, ?, 'blue', NULL)", [b, b + "r", b, b + "u"])
    for bk in ("A", "B", "C"):                                   # b1: three sportsbooks
        c.execute("INSERT INTO odds_books VALUES ('b1', ?, 'b1r', 1.5, 'close', 'bfo', NULL), ('b1', ?, 'b1u', 2.8, 'close', 'bfo', NULL)", [bk, bk])
    c.execute("INSERT INTO odds_books VALUES ('b1', 'Kalshi', 'b1r', 9.0, 'close', 'bfo', NULL), ('b1', 'Kalshi', 'b1u', 1.1, 'close', 'bfo', NULL)")
    c.execute("INSERT INTO odds_snapshots VALUES ('b3', 'x', NULL, 'b3r', 2.0, 'unknown'), ('b3', 'x', NULL, 'b3u', 2.0, 'unknown')")
    c.close()
    o = duckdb.connect(oc)
    o.execute("""CREATE TABLE odds_open_close (bout_id VARCHAR, red VARCHAR, blue VARCHAR, date DATE, mu BIGINT, open_red DOUBLE, open_blue DOUBLE,
                 low_red DOUBLE, high_red DOUBLE, low_blue DOUBLE, high_blue DOUBLE)""")
    o.execute("INSERT INTO odds_open_close VALUES ('b2', 'b2r', 'b2u', NULL, 1, 1.9, 1.95, 1.8, 2.0, 1.9, 2.0)")
    o.close()
    m = B.MarketOfRecord(main, oc)
    p, src = m.close("b1")
    assert src == "books" and p == pytest.approx(B.devig(1.5, 2.8))           # the exchange row is ignored
    assert m.close("b2")[1] == "range" and m.close("b2")[0] == pytest.approx(B.devig(1.9, 1.95))
    assert m.open("b2") == pytest.approx(B.devig(1.9, 1.95))
    assert m.close("b3") == (0.5, "old") and m.close("b4") == (None, None)
    assert m.best("b1") == (1.5, 2.8) and m.best("b3") is None
