"""Replay a past event: predict every bout using only data before the event, then compare with what happened.

One event is a handful of bouts, so this is a sanity check and a demonstration, not evidence about the model.
"""
import math

from ufcmodel.reports.fightweek import predict_card

KEY = ["A_KO", "A_SUB", "A_DEC", "B_KO", "B_SUB", "B_DEC"]


def replay(con, event_like: str):
    ev = con.execute("SELECT event_id, name, CAST(date AS VARCHAR) FROM events WHERE name LIKE ? ORDER BY date DESC LIMIT 1", [f"%{event_like}%"]).fetchone()
    if ev is None:
        raise SystemExit(f"no event matching {event_like!r}")
    eid, name, date = ev
    rows = con.execute("""
        SELECT f1.name, f2.name, b.weight_class, b.scheduled_rounds, r.result, b.method, b.method_detail, b.end_round, b.card_position
        FROM bouts b
        JOIN bout_fighter r ON r.bout_id = b.bout_id AND r.corner = 'red' JOIN bout_fighter u ON u.bout_id = b.bout_id AND u.corner = 'blue'
        JOIN fighters f1 ON f1.fighter_id = r.fighter_id JOIN fighters f2 ON f2.fighter_id = u.fighter_id
        WHERE b.event_id = ? ORDER BY b.card_position""", [eid]).fetchall()
    bouts = [dict(date=date, fighter_a=a, fighter_b=b, weight_class=wc, rounds=str(rd or 3)) for a, b, wc, rd, *_ in rows]
    preds, last = predict_card(con, bouts, before=date)
    out = []
    for (a, b, wc, rd, res, method, detail, end_round, pos), p in zip(rows, preds):
        pa = p["p"]
        six = p["sim"]["six"]
        cat = {"KO/TKO": 0, "Submission": 1, "Decision": 2}.get(method)
        winner = a if res == "win" else b if res == "loss" else None
        side = 0 if res == "win" else 3 if res == "loss" else None
        out.append(dict(a=a, b=b, wc=wc, sched=rd or 3, pos=pos, pa=pa, res=res, winner=winner, method=method, detail=detail,
                        end_round=end_round, p_distance=p["sim"]["p_distance"], p_round=p["sim"]["round"], six=six,
                        p_elo=p["p_elo"], p_actual_method=(six[side + cat] / six.sum() if side is not None and cat is not None else None),
                        p_method=[six[0] + six[3], six[1] + six[4], six[2] + six[5]], coverage=p["coverage"], flags=p["flags"]))
    return name, date, last, out


def summarize(name, date, last, out) -> str:
    L = [f"{name} ({date}). Data used: everything before {date} (latest fight in it: {last}). Odds not used: none exist for this date.", ""]
    dec = [o for o in out if o["winner"]]
    for o in out:
        pick = o["a"] if o["pa"] >= 0.5 else o["b"]
        p_pick = max(o["pa"], 1 - o["pa"])
        ok = "n/a" if o["winner"] is None else ("RIGHT" if pick == o["winner"] else "wrong")
        fin = f"{o['method']} (R{o['end_round']})" if o["method"] != "Decision" else "Decision"
        L.append(f"{o['a']} vs {o['b']} [{o['wc']}]: pick {pick} {p_pick:.0%} | actual {o['winner'] or o['res']} by {fin} | {ok}")
        mp = o["p_method"]
        L.append(f"    method model: KO {mp[0]:.0%}, Sub {mp[1]:.0%}, Dec {mp[2]:.0%}; goes the distance {o['p_distance']:.0%} "
                 f"(it {'did' if o['method'] == 'Decision' else 'did not'})")
    if dec:
        correct = sum(1 for o in dec if (o["pa"] >= 0.5) == (o["winner"] == o["a"]))
        ll = -sum(math.log(o["pa"] if o["winner"] == o["a"] else 1 - o["pa"]) for o in dec) / len(dec)
        br = sum((o["pa"] - (o["winner"] == o["a"])) ** 2 for o in dec) / len(dec)
        pm = [o["p_actual_method"] for o in out if o["p_actual_method"]]
        dist = [(o["p_distance"], o["method"] == "Decision") for o in out if o["method"] in ("Decision", "KO/TKO", "Submission")]
        L += ["", f"Winners picked: {correct} of {len(dec)}. Log loss {ll:.3f} (a coin flip is 0.693, the model's long-run average is about 0.64). "
              f"Brier {br:.3f} (coin flip 0.250).",
              f"Average probability the model gave to what actually happened (winner and method together): {sum(pm) / len(pm):.0%} "
              f"(six outcomes, so 17% is a coin-flip-sized guess).",
              f"Fights that went the distance: {sum(1 for _, d in dist if d)} of {len(dist)}; the model expected {sum(p for p, _ in dist):.1f}."]
    return "\n".join(L)


def replay_last(con, n=10):
    """The n most recent events that have results, each replayed with only the data before it."""
    names = [r[0] for r in con.execute(
        """SELECT e.name FROM events e JOIN bouts b USING (event_id) JOIN bout_fighter f USING (bout_id)
           WHERE f.result IN ('win', 'loss') GROUP BY e.name, e.date HAVING count(*) >= 6 ORDER BY e.date DESC LIMIT ?""", [n]).fetchall()]
    return [replay(con, nm) for nm in names]


def summarize_many(results) -> str:
    L = ["# Replay of recent events (each predicted using only data before it)", "",
         "| Event | Date | Bouts | Winners right | Log loss | Elo log loss |", "|---|---|---|---|---|---|"]
    allb = []
    for name, date, last, out in results:
        dec = [o for o in out if o["winner"]]
        if not dec:
            continue
        ok = sum(1 for o in dec if (o["pa"] >= 0.5) == (o["winner"] == o["a"]))
        y = [1.0 if o["winner"] == o["a"] else 0.0 for o in dec]
        ll = -sum(math.log(o["pa"] if yy else 1 - o["pa"]) for o, yy in zip(dec, y)) / len(dec)
        le = -sum(math.log(o["p_elo"] if yy else 1 - o["p_elo"]) for o, yy in zip(dec, y)) / len(dec)
        L.append(f"| {name[:46]} | {date} | {len(dec)} | {ok} | {ll:.3f} | {le:.3f} |")
        allb += [(o, yy) for o, yy in zip(dec, y)]
    n = len(allb)
    ok = sum(1 for o, yy in allb if (o["pa"] >= 0.5) == bool(yy))
    ll = -sum(math.log(o["pa"] if yy else 1 - o["pa"]) for o, yy in allb) / n
    le = -sum(math.log(o["p_elo"] if yy else 1 - o["p_elo"]) for o, yy in allb) / n
    br = sum((o["pa"] - yy) ** 2 for o, yy in allb) / n
    L += ["", f"**All {n} bouts:** winners right {ok} ({ok / n:.1%}); log loss {ll:.3f} (coin flip 0.693, Elo {le:.3f}, the model's long-run average about 0.64); "
          f"Brier {br:.3f} (coin flip 0.250).", ""]
    ci = 1.96 * math.sqrt(0.25 / n)
    L.append(f"With {n} bouts a coin flip would be right between {(0.5 - ci):.0%} and {(0.5 + ci):.0%} of the time, so accuracy alone can't separate skill from luck here.")
    L += ["", "By how confident the model was:", "", "| Model's confidence in its pick | Bouts | Picked right | Average confidence |", "|---|---|---|---|"]
    for lo, hi in ((0.5, 0.6), (0.6, 0.7), (0.7, 1.01)):
        sel = [(max(o["pa"], 1 - o["pa"]), (o["pa"] >= 0.5) == bool(yy)) for o, yy in allb if lo <= max(o["pa"], 1 - o["pa"]) < hi]
        if sel:
            L.append(f"| {lo:.0%} to {min(hi, 1):.0%} | {len(sel)} | {sum(1 for _, c in sel if c)} ({sum(1 for _, c in sel if c) / len(sel):.0%}) | {sum(c for c, _ in sel) / len(sel):.0%} |")
    fin = [o for o, _ in allb if o["method"] in ("Decision", "KO/TKO", "Submission")]
    pm = [o["p_actual_method"] for o in fin if o["p_actual_method"]]
    dist = sum(1 for o in fin if o["method"] == "Decision")
    L += ["", f"Method: average probability given to the winner and method that happened {sum(pm) / len(pm):.0%} (a blind guess among six is 17%). "
          f"Went the distance: {dist} of {len(fin)} ({dist / len(fin):.0%}); the model expected {sum(o['p_distance'] for o in fin):.1f} ({sum(o['p_distance'] for o in fin) / len(fin):.0%}).", ""]
    return "\n".join(L)
