"""Fight-week HTML report for a card. Needs `python -m ufcmodel phase10` run first (it writes the frozen settings).

Input CSV: date, fighter_a, fighter_b, weight_class, odds_a, odds_b (odds optional, decimal).
Models are refit on every bout in the database, so the report is only as current as the data. Optional column: rounds (3 or 5).
"""
import csv
import html
import json
import math
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from ufcmodel.eval.devig import shin
from ufcmodel.eval.phase10 import KEPT_COLS, Data, Model, _logit
from ufcmodel.eval.phase8 import finish_ratios, with_ratio
from ufcmodel.judging.round_score import fit_judging, load_decisions
from ufcmodel.sim.simulator import Params, calibrate, simulate
from ufcmodel.styles.archetypes import sm_features
from ufcmodel.features.asof import ALL_COLS, NAMES, bout_row, build_features, fighter_feats, load_raw
from ufcmodel.ingest.convert_ufc_data import slug

EDGE_FLAG = 0.05
LOW_COVERAGE = 3


def _sigmoid(z):
    return 1 / (1 + math.exp(-z))


def predict_card(con, bouts: list[dict], settings_dir="data/processed", before: str | None = None):
    """`before` (an ISO date) drops that day and everything later from the data, to replay a past card as it would have looked."""
    raw, statics = load_raw(con)
    if before:
        raw = [b for b in raw if b.date < before]
    rows, state = build_features(raw, statics, return_state=True)
    d = Data(rows)
    last_data = max(r.date for r in raw)
    chosen = json.load(open(Path(settings_dir) / "chosen_params.json"))
    stack = json.load(open(Path(settings_dir) / "stack.json"))
    last_fold = sorted(stack)[-1]
    w, coefs = stack[last_fold]
    models = {}
    for kind in ("lr", "lgbm"):
        start_year, C = chosen[kind][last_fold]
        tr = d.dec & (d.year >= start_year)
        models[kind] = Model(kind, KEPT_COLS, C).fit(d.X[tr], d.y[tr])
    known = set(statics) | set(state.hist)
    by_slug: dict[str, str] = {}
    counts = {fid: len(h) for fid, h in state.hist.items()}
    for fid, nm in con.execute("SELECT fighter_id, name FROM fighters").fetchall():
        by_slug[slug(nm)] = fid
    for al, fid in con.execute("SELECT alias, fighter_id FROM fighter_aliases").fetchall():
        k = slug(al)
        if k not in by_slug or counts.get(fid, 0) > counts.get(by_slug[k], 0):
            by_slug[k] = fid
    to_id = lambda name: by_slug.get(slug(name), "x-" + slug(name))
    w_j, kappa, _ = fit_judging(load_decisions(con), before or "9999-12-31")
    pool = [r for r in rows if r["stats_missing"] == 0 and r["method"] in ("KO/TKO", "Submission", "Decision") and r["sched"]]
    sim_p = calibrate(pool[-150:], Params(w=w_j, kappa=kappa))          # last 150 bouts, as tested
    finish_ratio = finish_ratios(pool[-1200:], sim_p) if len(pool) >= 300 else {}   # per-division finish multipliers
    out = []
    for b in bouts:
        a_id, b_id = to_id(b["fighter_a"]), to_id(b["fighter_b"])
        when = date.fromisoformat(b["date"])
        nb = SimpleNamespace(a=a_id, b=b_id, wc=b["weight_class"])
        row = bout_row(state, nb, when, statics)
        row.update(sm_features(d.style_model.weights([row["ax_a"]])[0], d.style_model.weights([row["ax_b"]])[0]))
        x = np.array([[row[c] for c in ALL_COLS]], float)
        p_lr, p_gb = models["lr"].predict(x)[0], models["lgbm"].predict(x)[0]
        rng = np.random.default_rng(0)
        sim_o = simulate(row["fa"], row["fb"], row["g15"], int(b.get("rounds") or 3), with_ratio(sim_p, finish_ratio, b["weight_class"]), 4000, rng)
        p_sim = sim_o["p_a"] / max(sim_o["p_a"] + sim_o["p_b"], 1e-9)
        z = (coefs["lr"] * _logit(p_lr) + coefs["lgbm"] * _logit(p_gb) + coefs["elo"] * _logit(row["elo_p"])
             + coefs.get("sim", 0.0) * _logit(p_sim))
        p_model = _sigmoid(z)
        oa = float(b["odds_a"]) if b.get("odds_a") else None
        ob = float(b["odds_b"]) if b.get("odds_b") else None
        p_mkt = shin(oa, ob)[0] if oa and ob else None
        p_final = _sigmoid(w * z + (1 - w) * _logit(p_mkt)) if p_mkt is not None else p_model
        contrib = models["lr"].contributions(x)[0]
        drivers = [(NAMES.get(models["lr"].cols[k], models["lr"].cols[k]), 100 * contrib[k] * p_lr * (1 - p_lr))
                   for k in np.argsort(-np.abs(contrib))[:5]]
        fa, fb = (fighter_feats(state, f, when, statics, float("nan")) for f in (a_id, b_id))
        flags = []
        for name, fid, f in ((b["fighter_a"], a_id, fa), (b["fighter_b"], b_id, fb)):
            if fid not in known:
                flags.append(f"{name}: not in the data (treated as a debutant)")
            elif f["n_bouts"] < LOW_COVERAGE:
                flags.append(f"{name}: only {int(f['n_bouts'])} bout(s) in the data")
            if not math.isnan(f["days_since"]) and f["days_since"] > 540:
                flags.append(f"{name}: layoff of {int(f['days_since'])} days (capped at 1500)")
            if math.isnan(f["age"]):
                flags.append(f"{name}: age unknown")
        gap = (when - date.fromisoformat(last_data)).days
        if gap > 30:
            flags.append(f"data ends {last_data}, {gap} days before this card: fights since then are not in the ratings")
        if oa is None:
            flags.append("no market odds supplied: no edge calculated")
        elif not 1.0 <= 1 / oa + 1 / ob <= 1.15:
            flags.append(f"odds look wrong: the two prices imply {1 / oa + 1 / ob:.2f} in total (a two-way market is about 1.02 to 1.10); check them")
        low = min(row["a_n"], row["b_n"]) < LOW_COVERAGE or a_id not in known or b_id not in known
        edges = {}
        if oa and ob:
            edges = {"A": p_final * oa - 1, "B": (1 - p_final) * ob - 1}
        arch_a = d.style_model.weights([row["ax_a"]])[0]
        arch_b = d.style_model.weights([row["ax_b"]])[0]
        inter = sorted(((NAMES.get(k, k), float(row[k])) for k in ("td_matchup", "str_matchup", "ctrl_matchup")), key=lambda t: -abs(t[1]))
        out.append(dict(p_elo=row["elo_p"], sim=sim_o, arch=(arch_a, arch_b), inter=inter, b=b, p=p_final, p_model=p_model, p_mkt=p_mkt, oa=oa, ob=ob, edges=edges, drivers=drivers,
                        flags=flags, coverage=(int(row["a_n"]), int(row["b_n"])), low=low,
                        thr=EDGE_FLAG * (2 if low else 1)))
    return out, last_data


def _pct(x):
    return "n/a" if x is None else f"{x:.1%}"


def render(results, last_data, title="Fight-week report") -> str:
    e = html.escape
    parts = [f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>
:root{{--bg:#fafaf8;--fg:#1b1b1a;--mut:#6b6b66;--line:#d8d8d2;--card:#fff;--warn:#9a5b00}}
@media(prefers-color-scheme:dark){{:root{{--bg:#161615;--fg:#ececea;--mut:#9a9a94;--line:#33332f;--card:#1f1f1d;--warn:#e0a24a}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif}}main{{max-width:880px;margin:0 auto;padding:16px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:14px 0}}
h1{{font-size:21px}}h2{{font-size:17px;margin:0 0 6px}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left}}
.mut{{color:var(--mut)}}.warn{{color:var(--warn)}}ul{{margin:4px 0 0;padding-left:20px}}</style></head><body><main>
<h1>{e(title)}</h1>
<p class="mut">Paper-trading output only. On the available data the model has not beaten the market (see docs/phase10_evaluation.md and
phase10_holdout.md), so nothing here is a bet recommendation. Data ends {e(last_data)}. Method and round probabilities come from the round-level simulator.</p>"""]
    for r in results:
        b = r["b"]
        a, c = e(b["fighter_a"]), e(b["fighter_b"])
        cand = [s for s, ed in r["edges"].items() if ed > r["thr"]]
        verdict = (f"Paper-trade candidate: {a if cand[0] == 'A' else c} (edge {r['edges'][cand[0]]:+.1%}, threshold {r['thr']:.0%})"
                   if cand else "No edge above threshold" if r["edges"] else "")
        parts.append(f"""<div class="card"><h2>{a} vs {c}</h2><div class="mut">{e(b['weight_class'])} &middot; {e(b['date'])} &middot;
coverage: {r['coverage'][0]} and {r['coverage'][1]} prior bouts{' &middot; <span class="warn">low confidence</span>' if r['low'] else ''}</div>
<table><tr><th></th><th>{a}</th><th>{c}</th></tr>
<tr><td>Win probability (model + market blend)</td><td>{_pct(r['p'])}</td><td>{_pct(1 - r['p'])}</td></tr>
<tr><td>Model alone</td><td>{_pct(r['p_model'])}</td><td>{_pct(1 - r['p_model'])}</td></tr>
<tr><td>Fair odds</td><td>{1 / r['p']:.2f}</td><td>{1 / (1 - r['p']):.2f}</td></tr>
<tr><td>Market odds (de-vigged probability)</td><td>{'n/a' if not r['oa'] else f"{r['oa']:.2f} ({_pct(r['p_mkt'])})"}</td><td>{'n/a' if not r['ob'] else f"{r['ob']:.2f} ({_pct(None if r['p_mkt'] is None else 1 - r['p_mkt'])})"}</td></tr>
<tr><td>Edge</td><td>{'n/a' if 'A' not in r['edges'] else f"{r['edges']['A']:+.1%}"}</td><td>{'n/a' if 'B' not in r['edges'] else f"{r['edges']['B']:+.1%}"}</td></tr></table>
<p><strong>{e(verdict)}</strong></p>
<div class="mut">Simulated outcome (calibrated round simulator; shown as probabilities for {a} / {c}):</div>
<table><tr><th>Method</th><th>{a}</th><th>{c}</th></tr>
<tr><td>KO/TKO</td><td>{r['sim']['six'][0]:.1%}</td><td>{r['sim']['six'][3]:.1%}</td></tr>
<tr><td>Submission</td><td>{r['sim']['six'][1]:.1%}</td><td>{r['sim']['six'][4]:.1%}</td></tr>
<tr><td>Decision</td><td>{r['sim']['six'][2]:.1%}</td><td>{r['sim']['six'][5]:.1%}</td></tr></table>
<p class="mut">Goes the distance: {r['sim']['p_distance']:.1%}. Finish by round: R1 {r['sim']['round'][0]:.1%}, R2 {r['sim']['round'][1]:.1%}, R3 {r['sim']['round'][2]:.1%}{f", R4 {r['sim']['round'][3]:.1%}, R5 {r['sim']['round'][4]:.1%}" if r['b'].get('rounds') == '5' else ''}.</p>
<p class="mut">Style weights (discovered styles 0 to 5), {a}: {' '.join(f"{x:.0%}" for x in r['arch'][0])}; {c}: {' '.join(f"{x:.0%}" for x in r['arch'][1])}. Largest style interactions (positive favours {a}): {'; '.join(f"{n} {v:+.2f}" for n, v in r['inter'])}.</p>
<div class="mut">Biggest drivers for {a} (logistic model, approximate points of win probability):</div><ul>{''.join(f"<li>{e(n)}: {pts:+.1f} points</li>" for n, pts in r['drivers'])}</ul>
{'<div class="warn">Flags</div><ul>' + ''.join(f'<li class="warn">{e(f)}</li>' for f in r['flags']) + '</ul>' if r['flags'] else ''}
</div>""")
    parts.append("</main></body></html>")
    return "".join(parts)


def build(con, csv_path, out_path) -> int:
    with open(csv_path, newline="", encoding="utf-8") as f:
        bouts = [r for r in csv.DictReader(line for line in f if not line.startswith("#"))]
    results, last = predict_card(con, bouts)
    Path(out_path).write_text(render(results, last, f"Fight-week report, {bouts[0]['date']}"), encoding="utf-8")
    return len(results)
