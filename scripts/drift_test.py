"""Finish-rate drift test (development folds only). Simulator variants differ only in how the per-division finish multipliers
are weighted by age. Success rule fixed in advance: goes-the-distance AND round-of-finish log loss must both improve against
the current setting with a paired-bootstrap interval below zero.

Usage: `python scripts/drift_test.py run <variant>` computes one variant (several can run side by side, read-only database);
`python scripts/drift_test.py report` compares whatever has finished.
"""
import pickle
import sys
from pathlib import Path

import duckdb
import numpy as np

from ufcmodel.eval import metrics as M

VARIANTS = {
    "base": ("current (last 1200 bouts, equal weight)", {}),
    "hl730": ("half-life 730 days, 1200 bouts", dict(half_life=730)),
    "hl365": ("half-life 365 days, 1200 bouts", dict(half_life=365)),
    "hl365w": ("half-life 365 days, 2400 bouts", dict(half_life=365, div_bouts=2400)),
    "hl180w": ("half-life 180 days, 2400 bouts", dict(half_life=180, div_bouts=2400)),
}
OUT = Path("data/processed/drift")


def run(key):
    from ufcmodel.eval.improvements2 import _metrics
    from ufcmodel.eval.phase8 import sim_walk_forward
    from ufcmodel.eval.phase10 import Data, holdout_start, make_folds
    from ufcmodel.features.asof import build_features, load_raw
    from ufcmodel.judging.round_score import load_decisions
    con = duckdb.connect("data/processed/ufc.duckdb", read_only=True)
    raw, statics = load_raw(con)
    d = Data(build_features(raw, statics))
    folds = make_folds(holdout_start(d.rows), False)
    dec = load_decisions(con)
    idx = [i for i in np.where(d.date >= folds[0][1])[0] if d.date[i] < folds[-1][2]]
    last_start = folds[-1][1]
    s = sim_walk_forward(d, folds, dec, **VARIANTS[key][1])
    m = _metrics(d, s, idx)
    m["last"] = _metrics(d, s, [i for i in idx if d.date[i] >= last_start])
    m["span"] = (folds[0][1], folds[-1][2], last_start)
    OUT.mkdir(parents=True, exist_ok=True)
    pickle.dump(m, open(OUT / f"{key}.pkl", "wb"))
    print("done", key, flush=True)


def report():
    out = {k: pickle.load(open(OUT / f"{k}.pkl", "rb")) for k in VARIANTS if (OUT / f"{k}.pkl").exists()}
    base = out["base"]
    span = base["span"]
    L = ["# Finish-rate drift test", "",
         f"Development folds {span[0]} to {span[1]}; last fold = {span[2]} onward. Differences are against the current setting "
         "(paired bootstrap, negative is better).", "",
         "| Variant | Round of finish | Goes the distance | Winner x method | Distance: expected vs actual (all) | Distance: expected vs actual (last fold) |",
         "|---|---|---|---|---|---|"]
    best = None
    for k, m in out.items():
        cells = []
        for q in ("llr", "lld", "ll6"):
            if m is base:
                cells.append(f"{m[q].mean():.4f}")
            else:
                dm, lo, hi = M.paired_bootstrap_diff(m[q], base[q])
                cells.append(f"{m[q].mean():.4f} ({dm:+.4f} [{lo:+.4f}, {hi:+.4f}])")
        L.append(f"| {VARIANTS[k][0]} | " + " | ".join(cells) + f" | {m['exp']:.1%} vs {m['obs']:.1%} | {m['last']['exp']:.1%} vs {m['last']['obs']:.1%} |")
        if m is not base:
            ok = M.paired_bootstrap_diff(m["lld"], base["lld"])[2] < 0 and M.paired_bootstrap_diff(m["llr"], base["llr"])[2] < 0
            if ok and (best is None or m["lld"].mean() < out[best]["lld"].mean()):
                best = k
    L += ["", f"Adopt: {VARIANTS[best][0] if best else 'nothing; the current calibration stands'}.", ""]
    Path("docs/drift_test.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    run(sys.argv[2]) if sys.argv[1] == "run" else report()
