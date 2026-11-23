import pytest

from ufcmodel.db import STAT_COLS, connect
from ufcmodel.qa.checks import run_checks


def _stats(**kw):
    base = dict.fromkeys(STAT_COLS, 0)
    base.update(kw)
    return base


def _insert(con, table, row):
    cols = ", ".join(row)
    con.execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))


@pytest.fixture
def con():
    c = connect(":memory:")
    c.execute("INSERT INTO events VALUES ('e1','UFC 1','2020-01-01','X','Y','Z')")
    c.execute("INSERT INTO bouts VALUES ('b1','e1','LW',false,3,'Decision',NULL,3,300,'Ref',1,NULL,NULL)")
    for fid, corner, res in (("f1", "red", "win"), ("f2", "blue", "loss")):
        c.execute("INSERT INTO bout_fighter VALUES ('b1',?,?,?)", [fid, corner, res])
        s = _stats(sig_l=10, sig_a=20, head_l=6, head_a=12, body_l=2, body_a=4, leg_l=2, leg_a=4,
                   dist_l=7, dist_a=14, clinch_l=2, clinch_a=4, ground_l=1, ground_a=2,
                   total_l=12, total_a=24, td_l=1, td_a=2, ctrl_sec=60)
        _insert(c, "rounds", {"bout_id": "b1", "fighter_id": fid, "round": 1, **s})
        _insert(c, "bout_totals", {"bout_id": "b1", "fighter_id": fid, **s})
    return c


def failures(con, **kw):
    return {r.name for r in run_checks(con, **kw) if r.failed}


def test_clean_data_passes(con):
    assert failures(con) == set()


def test_totals_mismatch(con):
    con.execute("UPDATE bout_totals SET sig_l = 11 WHERE fighter_id = 'f1'")
    assert "round_stats_sum_to_bout_totals" in failures(con)


def test_landed_exceeds_attempted(con):
    con.execute("UPDATE rounds SET td_l = 5 WHERE fighter_id = 'f1'")
    assert "landed_le_attempted[rounds]" in failures(con)


def test_control_exceeds_round(con):
    con.execute("UPDATE rounds SET ctrl_sec = 301 WHERE fighter_id = 'f1'")
    assert "control_time_le_round_length" in failures(con)


def test_control_limited_by_early_finish(con):
    con.execute("UPDATE bouts SET method='KO/TKO', end_round=1, end_time_sec=50")
    assert "control_time_le_round_length" in failures(con)


def test_target_vs_position_mismatch(con):
    con.execute("UPDATE rounds SET dist_l = 8 WHERE fighter_id = 'f1'")
    assert "sig_strikes_by_target_equal_by_position" in failures(con)


def test_bout_needs_two_fighters(con):
    con.execute("DELETE FROM bout_fighter WHERE fighter_id = 'f2'")
    assert "bout_has_two_fighters_one_result" in failures(con)


def test_two_winners(con):
    con.execute("UPDATE bout_fighter SET result = 'win'")
    assert "bout_has_two_fighters_one_result" in failures(con)


def test_duplicate_event(con):
    con.execute("INSERT INTO events VALUES ('e2','UFC 1','2020-01-01','X','Y','Z')")
    assert "no_duplicate_events" in failures(con)


def test_duplicate_bout(con):
    con.execute("INSERT INTO bouts VALUES ('b2','e1','LW',false,3,'Decision',NULL,3,300,'Ref',2,NULL,NULL)")
    for fid, corner in (("f1", "red"), ("f2", "blue")):
        con.execute("INSERT INTO bout_fighter VALUES ('b2',?,?,'draw')", [fid, corner])
    assert "no_duplicate_bouts" in failures(con)


def test_fighter_twice_in_event_is_not_a_duplicate(con):
    c = con
    c.execute("INSERT INTO fighters (fighter_id) VALUES ('f3')")
    c.execute("INSERT INTO bouts VALUES ('b3','e1','LW',false,1,'Submission',NULL,1,60,'Ref',2,NULL,NULL)")
    for fid, corner, res in (("f1", "red", "win"), ("f3", "blue", "loss")):
        c.execute("INSERT INTO bout_fighter VALUES ('b3',?,?,?)", [fid, corner, res])
    assert "no_duplicate_bouts" not in failures(c)


def test_overround_flagged(con):
    for fid, price in (("f1", 1.5), ("f2", 2.5)):  # 1/1.5 + 1/2.5 = 1.067: plausible
        con.execute("INSERT INTO odds_snapshots VALUES ('b1','bk','2020-01-01 00:00',?,?,'closing')", [fid, price])
    assert "odds_overround_plausible" not in failures(con)
    con.execute("UPDATE odds_snapshots SET price_decimal = 2.5 WHERE fighter_id = 'f1'")  # 0.8 sum
    assert "odds_overround_plausible" in failures(con)
