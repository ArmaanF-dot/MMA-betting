"""Phase 8 fight simulator: round-level Monte Carlo driven by the as-of skills.

Scope vs the spec: the spec's second-by-second semi-Markov model over positions needs tagged position sequences, which do not
exist. Public data has strikes by position (distance/clinch/ground) and control seconds per round, not transitions. This
simulator therefore works per round on aggregate quantities (strikes, takedowns, control, knockdowns, submission attempts),
with fatigue (round slope), accumulated damage and the opponent's matching skill, then scores decisions with the judging model.
Finish hazards use two scalars (`c_ko`, `c_sub`) calibrated to the training set's observed finish rates. The positional
transition model remains future work (it needs the tagging programme).
"""
from dataclasses import dataclass

import numpy as np

DISPERSION = 6.0
REL = (0.3, 3.0)
METHODS = ("KO", "SUB", "DEC")


@dataclass
class Params:
    c_ko: float = 0.12
    c_sub: float = 0.18
    w: np.ndarray = None
    kappa: float = 1.0
    vol: float = 1.0       # strike-volume scale
    decay: float = 0.85    # finish hazard multiplier per round after the first
    sigma: float = 0.0     # sd of the fight-level log pace effect shared by all rounds


def _rel(x, g):
    return float(np.clip(x / g, *REL)) if g > 0 else 1.0


def _nb(rng, lam, n):
    return rng.poisson(rng.gamma(DISPERSION, np.maximum(lam, 1e-9) / DISPERSION, n))


def simulate(fa: dict, fb: dict, g: dict, sched, p: Params, n=1500, rng=None) -> dict:
    rng = rng or np.random.default_rng(0)
    R = 5 if sched == 5 else 3
    alive = np.ones(n, bool)
    winner = np.zeros(n)            # +1 A, -1 B, 0 undecided/draw
    method = np.full(n, -1)         # 0 KO, 1 SUB, 2 DEC
    fin_round = np.zeros(n, int)
    cum_a = np.zeros(n)
    cum_b = np.zeros(n)
    rounds = []
    fm_a = np.exp(rng.normal(0, p.sigma, n) - p.sigma**2 / 2) if p.sigma > 0 else 1.0
    fm_b = np.exp(rng.normal(0, p.sigma, n) - p.sigma**2 / 2) if p.sigma > 0 else 1.0
    tot_sig_a = np.zeros(n)
    tot_sig_b = np.zeros(n)
    rounds_alive = np.zeros(n)
    for r in range(1, R + 1):
        pace_a = np.clip(1 + (fa["pace_slope"] - 1) * min(r - 1, 2) / 2, 0.5, 1.3)
        pace_b = np.clip(1 + (fb["pace_slope"] - 1) * min(r - 1, 2) / 2, 0.5, 1.3)
        lam_a = (5 / 15) * g["sig"] * _rel(fa["sig_for"], g["sig"]) * _rel(fb["sig_against"], g["sig"]) * pace_a * p.vol
        lam_b = (5 / 15) * g["sig"] * _rel(fb["sig_for"], g["sig"]) * _rel(fa["sig_against"], g["sig"]) * pace_b * p.vol
        sig_a, sig_b = _nb(rng, lam_a * fm_a, n), _nb(rng, lam_b * fm_b, n)
        td_a = _nb(rng, (5 / 15) * g["td"] * _rel(fa["td_for"], g["td"]) * _rel(fb["td_against"], g["td"]), n)
        td_b = _nb(rng, (5 / 15) * g["td"] * _rel(fb["td_for"], g["td"]) * _rel(fa["td_against"], g["td"]), n)
        lc_a = (5 / 15) * g["ctrl"] * _rel(fa["ctrl_for"], g["ctrl"]) * _rel(fb["ctrl_against"], g["ctrl"])
        lc_b = (5 / 15) * g["ctrl"] * _rel(fb["ctrl_for"], g["ctrl"]) * _rel(fa["ctrl_against"], g["ctrl"])
        ctrl_a = rng.gamma(1.5, lc_a / 1.5, n) * np.where(td_a > 0, 1.6, 0.4)
        ctrl_b = rng.gamma(1.5, lc_b / 1.5, n) * np.where(td_b > 0, 1.6, 0.4)
        over = np.maximum(ctrl_a + ctrl_b, 1e-9)
        scale = np.minimum(1.0, 300.0 / over)
        ctrl_a, ctrl_b = ctrl_a * scale, ctrl_b * scale
        typical = g["sig"] * 5 / 15 * 3 + 1e-6
        dmg_to_b = 1 + 0.5 * cum_a / typical
        dmg_to_a = 1 + 0.5 * cum_b / typical
        kd_a = rng.poisson(sig_a * g["head_frac"] * (fa["power"] / 100) * _rel(fb["chin"], g["chin"]) * dmg_to_b)
        kd_b = rng.poisson(sig_b * g["head_frac"] * (fb["power"] / 100) * _rel(fa["chin"], g["chin"]) * dmg_to_a)
        dom_a = np.maximum(sig_a - sig_b, 0) / (sig_a + sig_b + 10.0)
        dom_b = np.maximum(sig_b - sig_a, 0) / (sig_a + sig_b + 10.0)
        sub_a = rng.poisson((5 / 15) * g["sub"] * _rel(fa["sub_for"], g["sub"]) * _rel(fb["sub_against"], g["sub"]) * (1 + ctrl_a / 150))
        sub_b = rng.poisson((5 / 15) * g["sub"] * _rel(fb["sub_for"], g["sub"]) * _rel(fa["sub_against"], g["sub"]) * (1 + ctrl_b / 150))
        rounds.append((sig_a - sig_b, kd_a - kd_b, td_a - td_b, ctrl_a - ctrl_b, sub_a - sub_b, alive.copy()))
        tot_sig_a += sig_a * alive
        tot_sig_b += sig_b * alive
        rounds_alive += alive
        rs = p.decay ** (r - 1)
        # finish events: first to happen wins the round
        inf = np.inf
        ev = np.full((4, n), inf)
        for k, (hazard, who) in enumerate((
                (1 - np.exp(-p.c_ko * rs * (kd_a + 0.35 * dom_a * 3)), 1), (1 - (1 - p.c_sub) ** (sub_a * rs), 1),
                (1 - np.exp(-p.c_ko * rs * (kd_b + 0.35 * dom_b * 3)), -1), (1 - (1 - p.c_sub) ** (sub_b * rs), -1))):
            happens = (rng.random(n) < hazard) & alive
            ev[k] = np.where(happens, rng.random(n), inf)
        first = ev.argmin(axis=0)
        occurs = np.isfinite(ev.min(axis=0))
        who = np.where(first < 2, 1, -1)
        meth = np.where(first % 2 == 0, 0, 1)
        done = occurs & alive
        winner[done], method[done], fin_round[done] = who[done], meth[done], r
        alive &= ~done
        cum_a += sig_a
        cum_b += sig_b
    # decisions for fights that went the distance, three judges
    dec = alive
    if dec.any():
        sa = np.zeros((len(rounds), n))
        for i, (ds, dk, dt, dc, db_, alive_r) in enumerate(rounds):
            x = np.stack([ds / 10.0, dk, dt, dc / 60.0, db_], axis=1)
            sa[i] = 1 / (1 + np.exp(-p.kappa * (x @ p.w)))
        votes_a = np.zeros(n)
        votes_b = np.zeros(n)
        for _ in range(3):
            won = (rng.random(sa.shape) < sa)
            na = won.sum(axis=0)
            nb = len(rounds) - na
            votes_a += na > nb
            votes_b += nb > na
        winner[dec] = np.where((votes_a >= 2) & (votes_a > votes_b), 1, np.where((votes_b >= 2) & (votes_b > votes_a), -1, 0))[dec]
        method[dec] = 2
        fin_round[dec] = 0
    out = dict(p_a=float((winner == 1).mean()), p_b=float((winner == -1).mean()), p_draw=float(((winner == 0) & dec).mean()))
    out["six"] = np.array([((winner == s) & (method == m)).mean() for s in (1, -1) for m in (0, 1, 2)])
    out["round"] = np.array([(fin_round == r).mean() for r in range(1, 6)] + [dec.mean()])
    out["p_distance"] = float(dec.mean())
    out["sig_a"], out["sig_b"], out["dec"], out["rounds_alive"] = tot_sig_a, tot_sig_b, dec, rounds_alive
    return out


def observed_rates(rows_train) -> tuple[float, float]:
    ko = sum(1 for r in rows_train if r["method"] == "KO/TKO")
    sub = sum(1 for r in rows_train if r["method"] == "Submission")
    return ko / len(rows_train), sub / len(rows_train)


def calibrate(sample_rows, p: Params, n=400, iters=5, seed=0) -> Params:
    """Fixed-point on four scalars so the sample's simulated KO rate, submission rate, round-1 share of finishes and
    strikes per five minutes match what was observed."""
    obs_ko, obs_sub = observed_rates(sample_rows)
    fin = [r for r in sample_rows if r["method"] in ("KO/TKO", "Submission") and r["end_round"]]
    obs_r1 = sum(1 for r in fin if r["end_round"] == 1) / max(len(fin), 1)
    timed = [r for r in sample_rows if r.get("sig_obs_a") is not None and r.get("fight_sec")]
    obs_rate = sum(r["sig_obs_a"] + r["sig_obs_b"] for r in timed) / max(2 * sum(r["fight_sec"] / 300 for r in timed), 1e-9)
    rng = np.random.default_rng(seed)
    dec_obs = [r for r in sample_rows if r["method"] == "Decision" and r.get("sig_obs_a") is not None][:150]

    def coverage(sigma):
        q = Params(**{**p.__dict__, "sigma": sigma})
        hit = tot = 0
        for r in dec_obs:
            o = simulate(r["fa"], r["fb"], r["g15"], r["sched"], q, 200, rng)
            keep = o["dec"] if o["dec"].sum() >= 20 else np.ones_like(o["dec"])
            for obs, arr in ((r["sig_obs_a"], o["sig_a"][keep]), (r["sig_obs_b"], o["sig_b"][keep])):
                lo, hi = np.percentile(arr, [10, 90])
                hit += lo <= obs <= hi
                tot += 1
        return hit / max(tot, 1)

    for stage in range(2):
        for _ in range(iters if stage == 0 else 2):
            ko = sub = r1 = sig = alive_r = 0.0
            for r in sample_rows:
                o = simulate(r["fa"], r["fb"], r["g15"], r["sched"], p, n, rng)
                ko += o["six"][0] + o["six"][3]
                sub += o["six"][1] + o["six"][4]
                fr = 1 - o["round"][5]
                r1 += o["round"][0] / fr if fr > 0 else 0
                sig += (o["sig_a"].sum() + o["sig_b"].sum()) / n
                alive_r += 2 * o["rounds_alive"].sum() / n
            m = len(sample_rows)
            p.c_ko = float(np.clip(p.c_ko * obs_ko / max(ko / m, 1e-6), 0.01, 3.0))
            p.c_sub = float(np.clip(p.c_sub * obs_sub / max(sub / m, 1e-6), 0.01, 0.99))
            p.decay = float(np.clip(p.decay * (r1 / m) / max(obs_r1, 1e-6), 0.4, 1.2))
            p.vol = float(np.clip(p.vol * obs_rate / max(sig / alive_r, 1e-6), 0.5, 2.0))
        if stage == 0 and len(dec_obs) >= 40:
            p.sigma = min((0.0, 0.15, 0.25, 0.35, 0.45, 0.6), key=lambda sg: abs(coverage(sg) - 0.8))
    return p
