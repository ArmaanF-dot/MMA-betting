import json

import pytest

from ufcmodel.betting.paper import gate, grade, kelly_stake, log_recommendation
from ufcmodel.db import connect
from ufcmodel.tagging.import_tags import cohens_kappa, field_kappas, load_tag_files, takedown_crosscheck


def test_kappa_perfect_chance_and_partial():
    assert cohens_kappa(list("aabb"), list("aabb")) == 1.0
    assert cohens_kappa(list("aabb"), list("abab")) == pytest.approx(0.0)
    assert 0 < cohens_kappa(list("aaabbb"), list("aaabba")) < 1


def _doc(bout, events):
    return {"bout_id": bout, "tagger": "armaan", "events": events}


def test_import_and_crosscheck(tmp_path):
    con = connect(":memory:")
    con.execute("INSERT INTO bout_fighter VALUES ('b1','f1','red','win'), ('b1','f2','blue','loss')")
    con.execute("INSERT INTO bout_totals (bout_id, fighter_id, td_l) VALUES ('b1','f1',2), ('b1','f2',0)")
    ev = [{"round": 1, "t": 30, "type": "takedown_attempt", "fighter": "A", "result": "landed", "location": "cage"},
          {"round": 2, "t": 90, "type": "takedown_attempt", "fighter": "A", "result": "stuffed", "location": "open"}]
    (tmp_path / "b1.json").write_text(json.dumps(_doc("b1", ev)), encoding="utf-8")
    assert load_tag_files(con, tmp_path) == 2
    assert load_tag_files(con, tmp_path) == 2  # reloading replaces, never doubles
    assert con.execute("SELECT count(*) FROM tags").fetchone()[0] == 2
    assert takedown_crosscheck(con) == [("b1", "A", 1, 2)]  # tagged 1 landed, UFCStats says 2


def test_field_kappas_flag_unreliable_field(tmp_path):
    con = connect(":memory:")
    for p, locs in ((1, ["cage", "open", "cage", "open", "cage", "open"]), (2, ["cage", "open", "cage", "open", "open", "cage"])):
        evs = [{"round": 1, "t": i * 10, "type": "takedown_attempt", "fighter": "A", "location": loc} for i, loc in enumerate(locs)]
        d = tmp_path / f"p{p}"
        d.mkdir()
        (d / "b1.json").write_text(json.dumps(_doc("b1", evs)), encoding="utf-8")
        load_tag_files(con, d, pass_no=p)
    k = field_kappas(con, ["b1"])
    assert k["takedown_attempt.fighter"][0] == 1.0 and k["takedown_attempt.fighter"][2]
    assert not k["takedown_attempt.location"][2]  # 4 of 6 agree: kappa below 0.6


def test_kelly_caps_and_no_edge():
    assert kelly_stake(0.5, 2.0) == 0.0
    assert kelly_stake(0.9, 2.0) == 0.02
    assert kelly_stake(0.53, 2.0) == pytest.approx(0.25 * 0.06)  # edge 6%, below the 2% cap


def test_paper_log_grade_and_gate(tmp_path):
    log = tmp_path / "log.csv"
    for i in range(120):
        log_recommendation(log, "2026-01-01T00:00", f"ev{i % 10}", f"b{i}", "A", "bk", 2.2, 0.5)
    winners = {f"b{i}": "A" if i % 2 else "B" for i in range(120)}
    closing = {f"b{i}": {"A": 1.9, "B": 2.0} for i in range(120)}  # we took 2.2 vs a ~1.9 close: positive CLV
    g = gate(grade(log, winners, closing))
    assert g["passed"] and g["clv_lo"] > 0 and g["events"] == 10
    # same bets, closing price better than ours: gate must fail
    bad = gate(grade(log, winners, {f"b{i}": {"A": 2.6, "B": 1.6} for i in range(120)}))
    assert not bad["passed"]
    assert not gate(grade(log, winners, {}))["passed"]
