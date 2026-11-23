"""Phase 4 acceptance: does each skill component predict its own target better than a division-average model, as-of?

Targets, per fighter-fight on held-out bouts (2015 on): significant strikes landed, takedowns landed, knockdowns landed.
Skill model: expected = minutes/15 x global rate x (attacker's adjusted offence / global) x (defender's adjusted
defence / global), clipped. Baseline: expected = minutes/15 x the as-of mean rate of the fighter's division. Both use only data
before the bout. Scored by Poisson deviance with a paired bootstrap. Also writes a skill-trajectory sheet for a sense check.
"""
from collections import defaultdict

import numpy as np

from ufcmodel.eval import metrics as M

# (title, observed key, attacker skill, defender skill, unused, reference: global per-15 rate or the row's power/chin globals)
TARGETS = (("Significant strikes landed", "sig_obs", "sig_for", "sig_against", "sig_l", "g15"),
           ("Takedowns landed", "td_obs", "td_for", "td_against", "td_l", "g15"),
           ("Knockdowns landed (power x chin, per head strike: the model's version)", "kd_obs", "power", "chin", "kd", "pc"),
           ("Knockdowns landed (per-15 rate version, rejected)", "kd_obs", "kd__for", "kd__against", "kd", "g15"))
FAMOUS = ["Jon Jones", "Khabib Nurmagomedov", "Israel Adesanya", "Alex Pereira", "Islam Makhachev", "Conor McGregor",
          "Georges St-Pierre", "Anderson Silva", "Valentina Shevchenko", "Charles Oliveira"]
SKILLS = [("Elo", "elo"), ("Strike offence /15", "sig_for"), ("Strike defence (absorbed /15)", "sig_against"), ("Power", "power"),
          ("Chin (KD taken per 100 head)", "chin"), ("Takedown offence /15", "td_for"), ("Takedown defence (absorbed /15)", "td_against"),
          ("Control s /15", "ctrl_for"), ("Sub attempts /15", "sub_for"), ("Cardio slope", "pace_slope")]


def poisson_dev(y, mu):
    y, mu = np.asarray(y, float), np.maximum(np.asarray(mu, float), 1e-6)
    t = np.where(y > 0, y * np.log(np.maximum(y, 1e-9) / mu), 0.0)
    return 2 * (t - (y - mu))


def evaluate(rows, start="2015-01-01", end="9999") -> str:
    # as-of division and global means (per 15 min), updated after each event date
    div = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    glob = defaultdict(lambda: [0.0, 0.0])
    res = {t[0]: ([], [], []) for t in TARGETS}   # model dev, baseline dev, division of each obs
    by_date = defaultdict(list)
    for r in rows:
        by_date[r["date"]].append(r)
    for dte in sorted(by_date):
        batch = by_date[dte]
        for r in batch:
            m = (r["fight_sec"] or 0) / 60
            if m <= 0 or r["stats_missing"] == 1 or not (start <= dte < end):
                continue
            for title, obs, off, dfn, _, ref in TARGETS:
                g_tot, g_min = glob[obs]
                if g_min < 500:
                    continue
                g15 = 15 * g_tot / g_min
                dtot, dmin = div[obs][r["wc"]]
                base15 = 15 * dtot / dmin if dmin > 200 else g15
                for who, opp, y in (("fa", "fb", r[f"{obs}_a"]), ("fb", "fa", r[f"{obs}_b"])):
                    if y is None:
                        continue
                    ro, rd = (r["g15"]["power"], r["g15"]["chin"]) if ref == "pc" else (g15, g15)
                    rel = lambda x, g: float(np.clip(x / g, 0.3, 3.0)) if g > 0 else 1.0
                    mu = m / 15 * g15 * rel(r[who][off], ro) * rel(r[opp][dfn], rd)
                    res[title][0].append(poisson_dev(y, mu))
                    res[title][1].append(poisson_dev(y, m / 15 * base15))
                    res[title][2].append(r["wc"])
        for r in batch:   # update after the whole date is scored
            m = (r["fight_sec"] or 0) / 60
            if m <= 0 or r["stats_missing"] == 1:
                continue
            for obs in {t[1] for t in TARGETS}:
                for y in (r[f"{obs}_a"], r[f"{obs}_b"]):
                    if y is not None:
                        glob[obs][0] += y
                        glob[obs][1] += m
                        div[obs][r["wc"]][0] += y
                        div[obs][r["wc"]][1] += m
    L = ["# Phase 4 acceptance: skill components vs a division-average model", "",
         "Held-out fighter-fights from 2015 on, everything as-of. Mean Poisson deviance (lower is better); the difference is "
         "skill model minus division average with a paired bootstrap 95% interval (negative = skills help).", "",
         "| Target | n | Skill model | Division average | Difference [95% CI] | Verdict |", "|---|---|---|---|---|---|"]
    for title, (a, b, _) in res.items():
        a, b = np.array(a), np.array(b)
        m, lo, hi = M.paired_bootstrap_diff(a, b)
        L.append(f"| {title} | {len(a)} | {a.mean():.3f} | {b.mean():.3f} | {m:+.3f} [{lo:+.3f}, {hi:+.3f}] | {'better' if hi < 0 else 'not better'} |")
    L += ["", "Finishes (KO/TKO, submission, decision) are scored in `docs/phase8_simulator.md` against base rates. "
          "Posterior predictive checks (strike-total coverage by division) are there too.", ""]
    return "\n".join(L)


def skill_sheet(rows, names: dict, wanted=FAMOUS) -> str:
    """Skills as-of the first bout, the middle, and the latest bout of each named fighter, for Armaan to sense-check."""
    by = defaultdict(list)
    for r in rows:
        by[r["a"]].append((r["date"], r["fa"]))
        by[r["b"]].append((r["date"], r["fb"]))
    id_of = {n.lower(): i for i, n in names.items()}
    L = ["# Skill trajectories for a sense check", "",
         "Each fighter's opponent-adjusted skills as they stood going into their 3rd UFC bout, their middle bout, and their latest. "
         "Please tell me which look wrong; those are the ones to investigate.", ""]
    for n in wanted:
        fid = id_of.get(n.lower())
        if fid is None or len(by[fid]) < 3:
            L += [f"## {n}", "", "Not found, or fewer than 3 bouts in the data.", ""]
            continue
        h = sorted(by[fid], key=lambda t: t[0])
        pts = [h[2], h[len(h) // 2], h[-1]]
        L += [f"## {n} ({len(h)} bouts)", "", "| Skill | " + " | ".join(p[0] for p in pts) + " |", "|---|" + "---|" * len(pts)]
        for label, key in SKILLS:
            L.append(f"| {label} | " + " | ".join(f"{p[1][key]:.2f}" for p in pts) + " |")
        L.append("")
    return "\n".join(L)
