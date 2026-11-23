"""Paper-trading log, grading and the Phase 11 gate. No real-money output: this only records and grades recommendations."""
import csv
import math
from pathlib import Path

import numpy as np

COLS = ["ts", "event", "bout", "side", "bookmaker", "price", "model_p", "edge", "stake_frac"]
GRADED = COLS + ["won", "profit_flat", "closing_fair_p", "clv"]


def kelly_stake(p: float, odds: float, kappa: float = 0.25, cap: float = 0.02) -> float:
    return max(0.0, min(cap, kappa * (p * odds - 1) / (odds - 1)))


def log_recommendation(path, ts, event, bout, side, bookmaker, price, model_p):
    path = Path(path)
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(COLS)
        w.writerow([ts, event, bout, side, bookmaker, price, round(model_p, 4), round(model_p * price - 1, 4),
                    round(kelly_stake(model_p, price), 4)])


def grade(path, winners: dict, closing: dict) -> list[dict]:
    """winners: {bout: side that won}; closing: {bout: {'A': price, 'B': price}} (de-vigged here by normalising).
    CLV = ln(price taken x closing fair probability of that side): above zero means the taken price beat the fair close."""
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["bout"] not in winners:
                continue
            price, side = float(r["price"]), r["side"]
            won = winners[r["bout"]] == side
            row = {**r, "won": won, "profit_flat": price - 1 if won else -1.0, "closing_fair_p": "", "clv": ""}
            c = closing.get(r["bout"])
            if c:
                qa, qb = 1 / c["A"], 1 / c["B"]
                fair = (qa if side == "A" else qb) / (qa + qb)
                row["closing_fair_p"], row["clv"] = fair, math.log(price * fair)
            out.append(row)
    return out


def gate(graded: list[dict], min_events=8, min_bets=100, seed=0) -> dict:
    """Phase 11 gate: mean CLV with its 95% interval above zero, over enough events or bets (whichever is later)."""
    clv = np.array([float(r["clv"]) for r in graded if r["clv"] != ""])
    events = len({r["event"] for r in graded})
    enough = events >= min_events and len(graded) >= min_bets
    if len(clv) < 2:
        return dict(passed=False, n=len(graded), events=events, reason="no closing prices graded")
    rng = np.random.default_rng(seed)
    boots = clv[rng.integers(0, len(clv), (5000, len(clv)))].mean(axis=1)
    lo, hi = float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))
    roi = float(np.mean([r["profit_flat"] for r in graded]))
    return dict(passed=bool(enough and lo > 0), n=len(graded), events=events, enough_sample=enough,
                clv_mean=float(clv.mean()), clv_lo=lo, clv_hi=hi, flat_roi=roi)
