import math
import random
from pathlib import Path

import pytest

from ufcmodel.config import ROOT
from ufcmodel.features.asof import ALL_COLS, ANTI_IDX, RawBout, build_features


def synthetic(n_events=40, per_event=4, seed=0):
    rng = random.Random(seed)
    fighters = [f"f{i}" for i in range(30)]
    statics = {f: (f"{rng.randint(1975, 1995)}-06-01", rng.uniform(165, 195), rng.uniform(165, 200),
                   rng.choice(["Orthodox", "Southpaw", "Switch", None])) for f in fighters}
    raw, k = [], 0
    for e in range(n_events):
        date = f"{2010 + e // 12}-{e % 12 + 1:02d}-15"
        pool = rng.sample(fighters, per_event * 2)
        for i in range(per_event):
            a, b = pool[2 * i], pool[2 * i + 1]
            def st():
                sig = rng.randint(10, 80)
                head, body = rng.randint(0, sig), 0
                body = rng.randint(0, sig - head)
                leg = sig - head - body
                dist = rng.randint(0, sig)
                clinch = rng.randint(0, sig - dist)
                return dict(kd=rng.randint(0, 2), sig_l=sig, sig_a=sig + 20, head_l=head, head_a=head + 5, body_l=body, body_a=body + 2,
                            leg_l=leg, leg_a=leg + 1, dist_l=dist, dist_a=dist + 3, clinch_l=clinch, clinch_a=clinch + 1,
                            ground_l=sig - dist - clinch, ground_a=sig - dist - clinch + 1, total_l=sig + 5, total_a=sig + 30,
                            td_l=rng.randint(0, 3), td_a=rng.randint(3, 6), sub_att=rng.randint(0, 2), rev=rng.randint(0, 1),
                            ctrl_sec=rng.randint(0, 200))
            sa, sb = st(), st()
            rr = lambda sd: [(max(sd["sig_l"] // 3, 1), 300)] * 3
            raw.append(RawBout(f"b{k}", f"e{e}", date, i, rng.choice(["Lightweight", "Welterweight", "Women's Flyweight"]),
                               a, b, rng.choice([0.0, 1.0, 0.5]), rng.choice(["KO/TKO", "Submission", "Decision"]),
                               3, 300, sa, sb, None, None, 900, f"ref{rng.randint(0, 3)}", bool(rng.randint(0, 1)), 3, "Las Vegas", rr(sa), rr(sb)))
            k += 1
    return raw, statics


def same(a, b):
    return (math.isnan(a) and math.isnan(b)) if isinstance(a, float) and isinstance(b, float) and (math.isnan(a) or math.isnan(b)) else a == b


def assert_no_leakage(raw, statics, sample):
    full = {r["bout_id"]: r for r in build_features(raw, statics)}
    for b in sample:
        kept = [x for x in raw if x.date < b.date or x.bout_id == b.bout_id or (x.date == b.date and x.event_id == b.event_id)]
        cut = {r["bout_id"]: r for r in build_features(kept, statics)}[b.bout_id]
        for col in ALL_COLS + ["elo_p", "a_n", "b_n", "unc_a", "unc_b"]:
            assert same(full[b.bout_id][col], cut[col]), (b.bout_id, col)


def test_features_unchanged_when_later_data_deleted():
    raw, statics = synthetic()
    sample = random.Random(1).sample(raw, 12)
    assert_no_leakage(raw, statics, sample)


def test_features_do_not_use_the_bout_own_result():
    raw, statics = synthetic()
    flipped = [RawBout(**{**b.__dict__, "score_a": None if b.bout_id == "b100" else b.score_a}) for b in raw]
    a = {r["bout_id"]: r for r in build_features(raw, statics)}["b100"]
    b = {r["bout_id"]: r for r in build_features(flipped, statics)}["b100"]
    assert all(same(a[c], b[c]) for c in ALL_COLS)


def test_antisymmetric_columns_flip_sign_when_corners_swap():
    raw, statics = synthetic()
    swapped = [RawBout(**{**b.__dict__, "a": b.b, "b": b.a, "score_a": None if b.score_a is None else 1 - b.score_a,
                          "stats_a": b.stats_b, "stats_b": b.stats_a,
                          "rounds_a": b.rounds_b, "rounds_b": b.rounds_a}) for b in raw]
    ra = {r["bout_id"]: r for r in build_features(raw, statics)}
    rb = {r["bout_id"]: r for r in build_features(swapped, statics)}
    for bid in ("b90", "b120", "b150"):
        for i in ANTI_IDX:
            c = ALL_COLS[i]
            x, y = ra[bid][c], rb[bid][c]
            assert (math.isnan(x) and math.isnan(y)) or x == pytest.approx(-y, abs=1e-9), c
        assert ra[bid]["elo_p"] == pytest.approx(1 - rb[bid]["elo_p"])


def test_real_data_no_leakage():
    db = ROOT / "data" / "processed" / "ufc.duckdb"
    if not db.exists():
        pytest.skip("database not built")
    import duckdb
    from ufcmodel.features.asof import load_raw
    con = duckdb.connect(str(db), read_only=True)
    raw, statics = load_raw(con)
    sample = random.Random(3).sample(raw, 10)
    assert_no_leakage(raw, statics, sample)
