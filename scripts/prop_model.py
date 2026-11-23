"""Walk-forward method/distance probabilities for the 2023 to 2025-10 folds (development only; each fold fit on earlier bouts).
Saves, per bout: P(goes the distance) and P(red wins inside the distance), P(blue wins inside) from the simulator, the direct
LightGBM models, and the base rates. Orientation: A = red corner."""
import pickle

import duckdb
import numpy as np

from ufcmodel.eval.phase8 import base_rates, direct_outcomes, sim_walk_forward
from ufcmodel.eval.phase10 import Data, holdout_start, make_folds
from ufcmodel.features.asof import build_features, load_raw
from ufcmodel.judging.round_score import load_decisions

con = duckdb.connect("data/processed/ufc.duckdb", read_only=True)
raw, statics = load_raw(con)
d = Data(build_features(raw, statics))
folds = [f for f in make_folds(holdout_start(d.rows), False) if f[2] > "2023-06-01"]
print("folds:", folds, flush=True)
sim = sim_walk_forward(d, folds, load_decisions(con))
six, rnd = direct_outcomes(d, folds)
bsix, brnd = base_rates(d, folds)
out = {}
for i in np.where(d.mask(folds[0][1], folds[-1][2]))[0]:
    if i not in sim:
        continue
    s = sim[i]["six"] / sim[i]["six"].sum()
    r = sim[i]["round"]
    r = r / r.sum()
    out[d.bid[i]] = dict(
        dist_sim=float(r[5]), dist_dir=float(rnd[i][5]) if i in rnd else None, dist_base=float(brnd[i][5]),
        a_in_sim=float(s[0] + s[1]), b_in_sim=float(s[3] + s[4]),
        a_in_dir=float(six[i][0] + six[i][1]) if i in six else None, b_in_dir=float(six[i][3] + six[i][4]) if i in six else None,
        a_in_base=float(bsix[i][0] + bsix[i][1]), b_in_base=float(bsix[i][3] + bsix[i][4]),
        sched=d.rows[i]["sched"], date=d.date[i])
pickle.dump(out, open("data/processed/prop_model.pkl", "wb"))
print("saved", len(out), "bouts", flush=True)
