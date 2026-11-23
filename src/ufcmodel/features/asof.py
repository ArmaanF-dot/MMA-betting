"""As-of feature store (Phases 2, 4 and 7, on per-round UFCStats data).

Every row is computed from events strictly before the bout's event date: fighter histories, global priors, Elo ratings,
referee tendencies and opponent factors are all updated only after an event's last bout has been featurised.
`tests/test_asof.py` rebuilds features after deleting later data and asserts the rows are identical.

Skills (Phase 4) are recency-weighted (half-life 24 months), opponent-adjusted rates shrunk to the as-of global rate; the
posterior-style uncertainty is `unc_*`. A full PyMC hierarchical NegBin fit is not used: it is too slow for walk-forward refits,
which the spec allows replacing with a filter-style update (see docs/decisions.md for what that does and does not cover).
"""
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from ufcmodel.ratings.elo2 import PARAMS as ELO2_PARAMS, Elo2, expected as elo2_expected

NAN = float("nan")
ELO_K = 64.0
HALF_LIFE_MONTHS = 24
P_MIN = 15.0           # pseudo-exposure (minutes) pulling a rate to the global rate
REC_PRIOR_N = 5.0
FAC_CLIP = (0.4, 2.5)
ADJ = ("sig_l", "td_l", "kd", "sub_att", "ctrl_sec")   # stats that get an opponent factor
RATE = ADJ + ("head_l", "ground_l", "rev")
SM_K = 6

WC_LB = {"Women's Strawweight": 115, "Women's Flyweight": 125, "Women's Bantamweight": 135, "Women's Featherweight": 145,
         "Strawweight": 115, "Flyweight": 125, "Bantamweight": 135, "Featherweight": 145, "Lightweight": 155, "Welterweight": 170,
         "Middleweight": 185, "Light Heavyweight": 205, "Heavyweight": 265, "Super Heavyweight": 300}
ALTITUDE_M = {"Las Vegas": 610, "Denver": 1609, "Mexico City": 2240, "Salt Lake City": 1288, "Calgary": 1045, "Edmonton": 668,
              "Sao Paulo": 760, "Curitiba": 934, "Brasilia": 1172, "Johannesburg": 1753, "Phoenix": 331, "Albuquerque": 1619,
              "Denver, Colorado": 1609, "Bogota": 2640, "Winnipeg": 239, "Vancouver": 2, "Perth": 31, "Abu Dhabi": 27,
              "London": 11, "Rio de Janeiro": 2, "Newark": 9, "New York": 10, "Houston": 13, "Anaheim": 48, "Boston": 43}

# per-fighter features, differenced (A - B) into d_<name>
FEATS = [
    "elo", "wr_decay", "wr_all", "ko_win", "sub_win", "dec_win", "ko_loss", "sub_loss",
    "n_bouts", "log_minutes", "debut", "minutes_stats", "avg_minutes",
    "days_since", "bouts_24m", "long_layoff",
    "age", "age_sq", "trend", "height", "reach", "orth", "south", "switch",
    "sig_for", "sig_against", "sig_acc", "sig_def", "power", "chin", "damage", "after_ko_loss",
    "td_for", "td_against", "td_acc", "td_def", "ctrl_for", "ctrl_against", "ground_per_ctrl", "sub_for", "sub_against", "rev_for",
    "pace_slope", "leg_share", "body_share", "dist_share", "clinch_share", "ground_share", "wc_delta",
    "sig_acc_adj", "sig_def_adj", "td_acc_adj", "td_def_adj", "elo2", "rd",
    "wr_q", "top_wr", "top_fights", "best_win", "sos", "untested",
]
J_STATS = ("sig_l", "td_l", "ctrl_sec")
J_COLS = [f"j_{s}_{k}" for s in J_STATS for k in ("off", "def")]
SM_COLS = [f"sm_{i}_{j}" for i in range(SM_K) for j in range(i + 1, SM_K)]
GROUPS = {
    "elo": ["d_elo"],
    "record": ["d_wr_decay", "d_wr_all", "d_ko_win", "d_sub_win", "d_dec_win", "d_ko_loss", "d_sub_loss"],
    "experience": ["d_n_bouts", "d_log_minutes", "d_debut", "d_minutes_stats", "any_debut", "stats_missing"],
    "activity": ["d_days_since", "d_bouts_24m", "d_long_layoff"],
    "age_growth": ["d_age", "d_age_sq", "age_missing", "d_trend"],
    "physical": ["d_height", "d_reach", "d_orth", "d_south", "d_switch"],
    "striking": ["d_sig_for", "d_sig_against", "d_sig_acc", "d_sig_def"],
    "durability": ["d_power", "d_chin", "d_damage", "d_after_ko_loss"],
    "grappling": ["d_td_for", "d_td_against", "d_td_acc", "d_td_def", "d_ctrl_for", "d_ctrl_against", "d_ground_per_ctrl",
                  "d_sub_for", "d_sub_against", "d_rev_for"],
    "cardio": ["d_pace_slope", "d_avg_minutes"],
    "style_axes": ["d_leg_share", "d_body_share", "d_dist_share", "d_clinch_share", "d_ground_share"],
    "style_interactions": ["td_matchup", "str_matchup", "ctrl_matchup"],
    "style_matrix": SM_COLS,
    "acc_adjusted": ["d_sig_acc_adj", "d_sig_def_adj", "d_td_acc_adj", "d_td_def_adj"],
    "elo2": ["d_elo2", "d_rd"],
    "joint_adj": J_COLS,
    "age_style": ["d_age_x_ctrl", "d_age_x_power", "d_age_x_dist", "d_age_x_damage", "d_age_x_koloss", "d_age_x_wc"],
    "quality": ["d_wr_q", "d_top_wr", "d_top_fights", "d_best_win", "d_sos", "d_untested"],    "context": ["wc_ord", "is_women", "orth_vs_south", "d_wc_delta", "ref_finish", "is_title", "five_round", "main_event",
                "altitude", "alt_x_pace"],
}
SYMMETRIC = {"wc_ord", "is_women", "any_debut", "stats_missing", "age_missing", "ref_finish", "is_title", "five_round",
             "main_event", "altitude"}
ALL_COLS = [c for g in GROUPS.values() for c in g]
ANTI_IDX = [i for i, c in enumerate(ALL_COLS) if c not in SYMMETRIC]
AXES = ["dist_share", "clinch_share", "ground_share", "leg_share", "body_share", "sig_for", "power", "td_for", "ctrl_for",
        "ground_per_ctrl", "sub_for", "rev_for", "sig_def", "td_def", "pace_slope", "sig_acc"]

NAMES = {
    "d_sig_acc_adj": "striking accuracy (opponent-adjusted)", "d_sig_def_adj": "striking defence (opponent-adjusted)",
    "d_td_acc_adj": "takedown accuracy (opponent-adjusted)", "d_td_def_adj": "takedown defence (opponent-adjusted)",
    "d_age_x_ctrl": "age x control game", "d_age_x_power": "age x power", "d_age_x_dist": "age x distance striking",
    "d_age_x_damage": "age x head damage taken", "d_age_x_koloss": "age x KO losses", "d_age_x_wc": "age x weight class",
    "d_elo2": "Elo2 rating", "d_rd": "rating uncertainty", "d_wr_q": "quality-weighted win rate",
    "d_top_wr": "record vs top opponents", "d_top_fights": "fights vs top opponents", "d_best_win": "best win (opponent rating)",
    "d_sos": "strength of schedule", "d_untested": "untested against top opposition",
    "j_sig_l_off": "striking offence (joint fit)", "j_sig_l_def": "striking defence (joint fit)",
    "j_td_l_off": "takedown offence (joint fit)", "j_td_l_def": "takedown defence (joint fit)",
    "j_ctrl_sec_off": "control offence (joint fit)", "j_ctrl_sec_def": "control defence (joint fit)",
    "d_elo": "Elo rating", "d_wr_decay": "recent win rate", "d_wr_all": "career win rate", "d_ko_win": "KO win rate",
    "d_sub_win": "submission win rate", "d_dec_win": "decision win rate", "d_ko_loss": "KO loss rate",
    "d_sub_loss": "submission loss rate", "d_n_bouts": "UFC experience", "d_log_minutes": "cage time",
    "d_debut": "debut status", "d_minutes_stats": "minutes with stats", "d_days_since": "days since last fight",
    "d_bouts_24m": "fights in last 24 months", "d_long_layoff": "long layoff", "d_age": "age", "d_age_sq": "age curve",
    "d_trend": "recent striking trend", "d_height": "height", "d_reach": "reach", "d_orth": "orthodox stance",
    "d_south": "southpaw stance", "d_switch": "switch stance", "d_sig_for": "adjusted strikes landed per 15 min",
    "d_sig_against": "adjusted strikes absorbed per 15 min", "d_sig_acc": "striking accuracy", "d_sig_def": "striking defence",
    "d_power": "knockdown power", "d_chin": "chin (knockdowns taken per head strike)", "d_damage": "head damage taken",
    "d_after_ko_loss": "coming off a KO loss", "d_td_for": "adjusted takedowns per 15 min", "d_td_against": "takedowns absorbed",
    "d_td_acc": "takedown accuracy", "d_td_def": "takedown defence", "d_ctrl_for": "adjusted control time",
    "d_ctrl_against": "control time conceded", "d_ground_per_ctrl": "ground strikes per control minute",
    "d_sub_for": "submission attempts", "d_sub_against": "submission attempts faced", "d_rev_for": "reversals",
    "d_pace_slope": "late-round output (cardio)", "d_avg_minutes": "average fight length", "d_leg_share": "leg-kick share",
    "d_body_share": "body-strike share", "d_dist_share": "distance striking share", "d_clinch_share": "clinch striking share",
    "d_ground_share": "ground striking share", "d_wc_delta": "weight-class move", "orth_vs_south": "orthodox vs southpaw matchup",
    "td_matchup": "takedown offence vs opponent's takedown defence", "str_matchup": "striking offence vs opponent's defence",
    "ctrl_matchup": "control offence vs opponent's control defence", "alt_x_pace": "altitude x cardio",
}


@dataclass
class RawBout:
    bout_id: str
    event_id: str
    date: str
    order: int
    wc: str
    a: str
    b: str
    score_a: float | None
    method: str
    end_round: int | None
    end_time: int | None
    stats_a: dict
    stats_b: dict
    odds_a: float | None = None
    odds_b: float | None = None
    fight_sec: float | None = None
    ref: str = ""
    is_title: bool = False
    sched: int | None = None
    city: str = ""
    rounds_a: list = field(default_factory=list)   # [(sig_landed, seconds)] per round
    rounds_b: list = field(default_factory=list)


@dataclass
class State:
    hist: dict = field(default_factory=lambda: defaultdict(list))
    elo: dict = field(default_factory=lambda: defaultdict(lambda: 1500.0))
    glob: dict = field(default_factory=dict)       # stat -> [sum, minutes]
    ref: dict = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    elo2: Elo2 = field(default_factory=lambda: Elo2(**ELO2_PARAMS))
    ref_glob: list = field(default_factory=lambda: [0, 0])


def load_raw(con):
    from ufcmodel.db import STAT_COLS
    cols = ", ".join(f"tr.{c}" for c in STAT_COLS) + ", " + ", ".join(f"tu.{c}" for c in STAT_COLS)
    rows = con.execute(f"""
        SELECT b.bout_id, b.event_id, CAST(e.date AS VARCHAR), b.card_position, b.weight_class,
               r.fighter_id, u.fighter_id, r.result, b.method, b.end_round, b.end_time_sec, b.fight_seconds,
               b.referee, b.is_title, b.scheduled_rounds, e.city, b.round_lengths, {cols}
        FROM bouts b JOIN events e USING (event_id)
        JOIN bout_fighter r ON r.bout_id = b.bout_id AND r.corner = 'red'
        JOIN bout_fighter u ON u.bout_id = b.bout_id AND u.corner = 'blue'
        LEFT JOIN bout_totals tr ON tr.bout_id = b.bout_id AND tr.fighter_id = r.fighter_id
        LEFT JOIN bout_totals tu ON tu.bout_id = b.bout_id AND tu.fighter_id = u.fighter_id
        ORDER BY e.date, b.event_id, b.card_position""").fetchall()
    rnd = defaultdict(list)
    for bid, fid, n, sig in con.execute("SELECT bout_id, fighter_id, round, sig_l FROM rounds ORDER BY bout_id, fighter_id, round").fetchall():
        rnd[(bid, fid)].append((n, sig))
    odds = defaultdict(dict)
    for bid, fid, p in con.execute("SELECT bout_id, fighter_id, price_decimal FROM odds_snapshots").fetchall():
        odds[bid][fid] = p
    score = {"win": 1.0, "loss": 0.0, "draw": 0.5, "nc": None}
    k = len(STAT_COLS)
    out = []
    for row in rows:
        (bid, ev, d, pos, wc, a, b, res, method, er, et, fs, ref, title, sched, city, lens) = row[:17]
        sa, sb = dict(zip(STAT_COLS, row[17:17 + k])), dict(zip(STAT_COLS, row[17 + k:17 + 2 * k]))
        lengths = [int(x) for x in lens.split(",")] if lens else None

        def sec_rounds(fid):
            res_ = []
            for n, sig in rnd.get((bid, fid), []):
                s = et if (n == er and et is not None) else ((lengths[n - 1] * 60) if lengths and n <= len(lengths) else 300)
                res_.append((sig, s))
            return res_
        o = odds.get(bid, {})
        out.append(RawBout(bid, ev, d, pos or 0, wc or "", a, b, score[res], method or "", er, et, sa, sb, o.get(a), o.get(b),
                           fs, ref or "", bool(title), sched, city or "", sec_rounds(a), sec_rounds(b)))
    statics = {}
    for fid, dob, h, r_, stance in con.execute("SELECT fighter_id, CAST(dob AS VARCHAR), height_cm, reach_cm, stance FROM fighters").fetchall():
        statics[fid] = (dob, h, r_, stance)
    return out, statics


def _minutes(b: RawBout) -> float:
    return b.fight_sec / 60 if b.fight_sec else NAN


def _cat(method: str) -> str:
    return {"KO/TKO": "KO", "Submission": "SUB", "Decision": "DEC"}.get(method, "OTHER")


def _shrunk(count, n, prior):
    return (count + REC_PRIOR_N * prior) / (n + REC_PRIOR_N)


def _g(state: State, key: str, per="min") -> float:
    tot, mins = state.glob.get(key, [0.0, 0.0])
    return tot / mins if mins > 0 else 0.0


def _gsum(state: State, key: str) -> float:
    return state.glob.get(key, [0.0, 0.0])[0]


def _ratio(num, den, default):
    return num / den if den > 0 else default


def fighter_feats(state: State, fid: str, d: date, statics: dict, wc_now: float) -> dict:
    hist = state.hist.get(fid, [])
    st = statics.get(fid, (None, None, None, None))
    n = len(hist)
    f: dict[str, float] = {"elo": state.elo[fid] if fid in state.elo else 1500.0, "n_bouts": float(n), "debut": float(n == 0)}
    w = [0.5 ** ((d - r["date"]).days / 30.44 / HALF_LIFE_MONTHS) for r in hist]
    sw = sum(w)
    f["wr_decay"] = (sum(wi * r["score"] for wi, r in zip(w, hist)) + 0.5) / (sw + 1.0)
    f["wr_all"] = _shrunk(sum(r["score"] for r in hist), n, 0.5)
    for key, cat, won, prior in (("ko_win", "KO", 1.0, 0.20), ("sub_win", "SUB", 1.0, 0.10), ("dec_win", "DEC", 1.0, 0.25),
                                 ("ko_loss", "KO", 0.0, 0.10), ("sub_loss", "SUB", 0.0, 0.07)):
        f[key] = _shrunk(sum(1 for r in hist if r["cat"] == cat and r["score"] == won), n, prior)
    mins = [r["minutes"] for r in hist if not math.isnan(r["minutes"])]
    f["log_minutes"] = math.log1p(sum(mins))
    f["avg_minutes"] = (sum(mins) + 10.0 * 8.0) / (len(mins) + 8.0)
    f["minutes_stats"] = sum(r["minutes"] for r in hist if r["has_stats"] and not math.isnan(r["minutes"]))
    if hist:
        f["days_since"] = float(min((d - hist[-1]["date"]).days, 1500))
        f["wc_delta"] = wc_now - hist[-1]["wc"] if not (math.isnan(wc_now) or math.isnan(hist[-1]["wc"])) else NAN
        f["after_ko_loss"] = float(hist[-1]["cat"] == "KO" and hist[-1]["score"] == 0.0)
    else:
        f["days_since"], f["wc_delta"], f["after_ko_loss"] = NAN, NAN, 0.0
    f["bouts_24m"] = float(sum(1 for r in hist if (d - r["date"]).days <= 730))
    f["long_layoff"] = float(not math.isnan(f["days_since"]) and f["days_since"] > 540)
    dob, h, rch, stance = st
    age = (d - date.fromisoformat(dob)).days / 365.25 if dob else NAN
    f["age"], f["age_sq"] = age, (age - 30) ** 2 if not math.isnan(age) else NAN
    f["height"], f["reach"] = (h if h is not None else NAN), (rch if rch is not None else NAN)
    f["orth"], f["south"], f["switch"] = (float(stance == "Orthodox"), float(stance == "Southpaw"), float(stance == "Switch")) \
        if stance else (NAN, NAN, NAN)

    usable = [(wi, r) for wi, r in zip(w, hist) if r["has_stats"] and not math.isnan(r["minutes"])]

    def adj_rate(stat, side, recs):
        lam0 = _g(state, stat)
        num, den = P_MIN * lam0, P_MIN
        counts = 0.0
        for wi, r in recs:
            x = r[side][stat]
            if x is None:
                continue
            fac = r["fac_for" if side == "for" else "fac_against"].get(stat, 1.0) if stat in ADJ else 1.0
            num += wi * x
            den += wi * r["minutes"] * fac
            counts += wi * x
        return 15.0 * num / den, counts, den

    rates = {}
    for stat in RATE:
        for side in ("for", "against"):
            rates[(stat, side)] = adj_rate(stat, side, usable)[0]
    f["sig_for"], f["sig_against"] = rates[("sig_l", "for")], rates[("sig_l", "against")]
    f["td_for"], f["td_against"] = rates[("td_l", "for")], rates[("td_l", "against")]
    f["ctrl_for"], f["ctrl_against"] = rates[("ctrl_sec", "for")], rates[("ctrl_sec", "against")]
    f["sub_for"], f["sub_against"] = rates[("sub_att", "for")], rates[("sub_att", "against")]
    f["rev_for"] = rates[("rev", "for")]
    for k in ("kd", "ctrl_sec", "sub_att", "td_l", "sig_l"):  # raw 'for/against' rates, exposed for opponent factors
        f[f"{k}__for"], f[f"{k}__against"] = rates[(k, "for")], rates[(k, "against")]
    _, counts, den = adj_rate("sig_l", "for", usable)
    f["unc_sig"] = 15.0 * math.sqrt(max(counts, 1.0)) / den * math.sqrt(1 + (f["days_since"] if not math.isnan(f["days_since"]) else 0) / 365)
    # accuracy and defence, binomial (landed out of attempted) shrunk to the as-of global ratio
    def acc(land, att, side, pa):
        ln = sum(wi * r[side][land] for wi, r in usable if r[side][land] is not None and r[side][att] is not None)
        at = sum(wi * r[side][att] for wi, r in usable if r[side][land] is not None and r[side][att] is not None)
        g_acc = _gsum(state, land) / _gsum(state, att) if _gsum(state, att) > 0 else 0.4
        return (ln + pa * g_acc) / (at + pa)
    f["sig_acc"], f["sig_def"] = acc("sig_l", "sig_a", "for", 100.0), 1 - acc("sig_l", "sig_a", "against", 100.0)
    f["td_acc"], f["td_def"] = acc("td_l", "td_a", "for", 8.0), 1 - acc("td_l", "td_a", "against", 8.0)
    # shares of significant strikes
    sig_tot = sum(wi * r["for"]["sig_l"] for wi, r in usable if r["for"]["sig_l"] is not None)
    for key, stat in (("leg_share", "leg_l"), ("body_share", "body_l"), ("dist_share", "dist_l"), ("clinch_share", "clinch_l"), ("ground_share", "ground_l")):
        x = sum(wi * r["for"][stat] for wi, r in usable if r["for"][stat] is not None and r["for"]["sig_l"] is not None)
        share0 = _gsum(state, stat) / _gsum(state, "sig_l") if _gsum(state, "sig_l") > 0 else 0.2
        f[key] = (x + 100.0 * share0) / (sig_tot + 100.0)
    # ground strikes per control minute, power and chin per head strike
    gl = sum(wi * r["for"]["ground_l"] for wi, r in usable if r["for"]["ground_l"] is not None and r["for"]["ctrl_sec"] is not None)
    cm = sum(wi * r["for"]["ctrl_sec"] / 60 for wi, r in usable if r["for"]["ground_l"] is not None and r["for"]["ctrl_sec"] is not None)
    g0 = _gsum(state, "ground_l") / (_gsum(state, "ctrl_sec") / 60) if _gsum(state, "ctrl_sec") > 0 else 5.0
    f["ground_per_ctrl"] = (gl + 3.0 * g0) / (cm + 3.0)
    k0 = _gsum(state, "kd") / _gsum(state, "head_l") if _gsum(state, "head_l") > 0 else 0.01
    for key, side in (("power", "for"), ("chin", "against")):
        kd = sum(wi * r[side]["kd"] for wi, r in usable if r[side]["kd"] is not None and r["for" if side == "for" else "against"]["head_l"] is not None)
        hd = sum(wi * r["for"]["head_l"] if side == "for" else wi * r["against"]["head_l"]
                 for wi, r in usable if r[side]["kd"] is not None and r["for" if side == "for" else "against"]["head_l"] is not None)
        f[key] = 100.0 * (kd + 300.0 * k0) / (hd + 300.0)
    f["damage"] = math.log1p(sum(r["against"]["head_l"] for r in hist if r["against"]["head_l"] is not None))
    # cardio: late-round vs first-round output
    ratios = []
    for wi, r in usable:
        sr = r["rounds_for"]
        if len(sr) >= 3 and sr[0][1] > 0 and sr[0][0] and all(s > 0 for _, s in sr):
            early = sr[0][0] / sr[0][1]
            late = sum(x for x, _ in sr[2:]) / sum(s for _, s in sr[2:])
            ratios.append((wi, min(max(late / early, 0.2), 3.0)))
    f["pace_slope"] = (sum(wi * x for wi, x in ratios) + 2.0) / (sum(wi for wi, _ in ratios) + 2.0)
    # trend: recent three fights' adjusted striking minus career
    last3 = [(1.0, r) for _, r in usable[-3:]]
    f["trend"] = adj_rate("sig_l", "for", last3)[0] - f["sig_for"] if last3 else 0.0

    # opponent-adjusted accuracy and defence: undo the defensive (or offensive) level of the opponents faced, in log-odds,
    # shrunk towards the global level with 2 pseudo-fights (improvement 1: stat padding against weak defenders)
    def lg(p):
        p = min(max(p, 1e-4), 1 - 1e-4)
        return math.log(p / (1 - p))

    def sg(z):
        return 1 / (1 + math.exp(-z))

    def opp_mean(key, glob_p):
        num = sum(wi * lg(r["opp_q"][key]) for wi, r in usable if r.get("opp_q"))
        den = sum(wi for wi, r in usable if r.get("opp_q"))
        return (num + 2.0 * lg(glob_p)) / (den + 2.0)

    g_sacc = _gsum(state, "sig_l") / _gsum(state, "sig_a") if _gsum(state, "sig_a") > 0 else 0.45
    g_tacc = _gsum(state, "td_l") / _gsum(state, "td_a") if _gsum(state, "td_a") > 0 else 0.35
    f["sig_acc_adj"] = sg(lg(f["sig_acc"]) + opp_mean("sig_def", 1 - g_sacc) - lg(1 - g_sacc))
    f["sig_def_adj"] = sg(lg(f["sig_def"]) + opp_mean("sig_acc", g_sacc) - lg(g_sacc))
    f["td_acc_adj"] = sg(lg(f["td_acc"]) + opp_mean("td_def", 1 - g_tacc) - lg(1 - g_tacc))
    f["td_def_adj"] = sg(lg(f["td_def"]) + opp_mean("td_acc", g_tacc) - lg(g_tacc))

    # improved Elo with margin of victory and rating deviation (improvement 2)
    f["elo2"], f["rd"] = state.elo2.state(fid, d)

    # quality of opposition (improvement 4): who the record was built against
    q_recs = [(wi, r) for wi, r in zip(w, hist) if r.get("opp_q")]
    qw = [(wi * math.exp((r["opp_q"]["elo"] - 1500) / 150), r) for wi, r in q_recs]
    f["wr_q"] = (sum(x * r["score"] for x, r in qw) + 0.5) / (sum(x for x, _ in qw) + 1.0)
    top = [r for _, r in q_recs if r["opp_q"]["elo"] >= 1600]
    f["top_fights"] = float(len(top))
    f["top_wr"] = (sum(r["score"] for r in top) + 0.5) / (len(top) + 1.0)
    wins = [r["opp_q"]["elo"] for _, r in q_recs if r["score"] == 1.0]
    f["best_win"] = max(wins) if wins else 1450.0
    f["sos"] = (sum(r["opp_q"]["elo"] for _, r in q_recs) + 3 * 1500.0) / (len(q_recs) + 3)
    f["untested"] = float(len(q_recs) >= 3 and max(r["opp_q"]["elo"] for _, r in q_recs) < 1580)
    return f


def _style_vec(f: dict) -> list[float]:
    return [f[a] for a in AXES]


def bout_row(state: State, bout, d: date, statics: dict) -> dict:
    wc = float(WC_LB.get(bout.wc, NAN))
    fa = fighter_feats(state, bout.a, d, statics, wc)
    fb = fighter_feats(state, bout.b, d, statics, wc)
    row = {f"d_{k}": fa[k] - fb[k] for k in FEATS}
    row["wc_ord"] = wc
    row["is_women"] = float(bout.wc.startswith("Women"))
    row["any_debut"] = float(fa["debut"] or fb["debut"])
    row["stats_missing"] = float(fa["minutes_stats"] == 0 or fb["minutes_stats"] == 0)
    row["age_missing"] = float(math.isnan(fa["age"]) or math.isnan(fb["age"]))
    row["orth_vs_south"] = (fa["orth"] * fb["south"] - fa["south"] * fb["orth"]) if not any(
        math.isnan(x) for x in (fa["orth"], fa["south"], fb["orth"], fb["south"])) else NAN
    gsig = max(_g(state, "sig_l") * 15, 1e-6)
    gtd = max(_g(state, "td_l") * 15, 1e-6)
    gctrl = max(_g(state, "ctrl_sec") * 15, 1e-6)
    row["td_matchup"] = (fa["td_for"] * fb["td_against"] - fb["td_for"] * fa["td_against"]) / (gtd * gtd)
    row["str_matchup"] = (fa["sig_for"] * fb["sig_against"] - fb["sig_for"] * fa["sig_against"]) / (gsig * gsig)
    row["ctrl_matchup"] = (fa["ctrl_for"] * fb["ctrl_against"] - fb["ctrl_for"] * fa["ctrl_against"]) / (gctrl * gctrl)
    # age curves that differ by style, and chin wear that bites harder with age (improvement 6)
    g_pow = 100 * _gsum(state, "kd") / _gsum(state, "head_l") if _gsum(state, "head_l") > 0 else 1.0

    def aged(f, x):
        return (f["age"] - 30) * x if not math.isnan(f["age"]) else NAN
    for name, fn in (("age_x_ctrl", lambda f: aged(f, f["ctrl_for"] / gctrl)), ("age_x_power", lambda f: aged(f, f["power"] / max(g_pow, 1e-6))),
                     ("age_x_dist", lambda f: aged(f, f["dist_share"])), ("age_x_damage", lambda f: aged(f, f["damage"])),
                     ("age_x_koloss", lambda f: aged(f, f["ko_loss"])),
                     ("age_x_wc", lambda f: aged(f, (wc - 170) / 50) if not math.isnan(wc) else NAN)):
        row[f"d_{name}"] = fn(fa) - fn(fb)
    ref = getattr(bout, "ref", "")
    n_ref, fin_ref = state.ref[ref] if ref in state.ref else (0, 0)
    gn, gf = state.ref_glob
    prior = gf / gn if gn else 0.5
    row["ref_finish"] = (fin_ref + 10 * prior) / (n_ref + 10)
    row["is_title"] = float(bool(getattr(bout, "is_title", False)))
    sched = getattr(bout, "sched", None)
    row["five_round"] = float(sched == 5)
    row["main_event"] = float(getattr(bout, "order", 0) == 1)
    alt = float(ALTITUDE_M.get(getattr(bout, "city", ""), 100))
    row["altitude"] = alt
    row["alt_x_pace"] = alt / 1000.0 * (fa["pace_slope"] - fb["pace_slope"])
    for c in SM_COLS:
        row[c] = 0.0
    row["elo_p"] = 1 / (1 + 10 ** ((fb["elo"] - fa["elo"]) / 400))
    row["elo2_p"] = elo2_expected(fa["elo2"], fb["elo2"], fa["rd"], fb["rd"])
    for c in J_COLS:
        row[c] = 0.0   # filled by add_joint_features after the pass
    row["a_n"], row["b_n"] = fa["n_bouts"], fb["n_bouts"]
    row["unc_a"], row["unc_b"] = fa["unc_sig"], fb["unc_sig"]
    row["ax_a"], row["ax_b"] = _style_vec(fa), _style_vec(fb)
    gh = _gsum(state, "head_l") / _gsum(state, "sig_l") if _gsum(state, "sig_l") > 0 else 0.7
    k0 = _gsum(state, "kd") / _gsum(state, "head_l") if _gsum(state, "head_l") > 0 else 0.01
    row["g15"] = dict(sig=gsig, td=gtd, ctrl=gctrl, sub=max(_g(state, "sub_att") * 15, 1e-6), head_frac=gh,
                      power=100 * k0, chin=100 * k0)
    row["fa"], row["fb"] = fa, fb   # per-fighter skills at this bout: used by the post-event update and the simulator
    return row


def _factor(state: State, fb: dict, stat: str, side: str) -> float:
    glob15 = _g(state, stat) * 15
    if glob15 <= 0:
        return 1.0
    return min(max(fb[f"{stat}__{side}"] / glob15, FAC_CLIP[0]), FAC_CLIP[1])


def _update(state: State, event: list[RawBout], rows: dict):
    upd = defaultdict(float)
    for b in event:
        if b.score_a is None:
            continue
        mins = _minutes(b)
        cat = _cat(b.method)
        d = date.fromisoformat(b.date)
        wc = float(WC_LB.get(b.wc, NAN))
        has = b.stats_a.get("sig_l") is not None and b.stats_b.get("sig_l") is not None and not math.isnan(mins)
        fa, fb = rows[b.bout_id]["fa"], rows[b.bout_id]["fb"]
        for me, sc, sa, sb, ra, opp_f, mine_f in ((b.a, b.score_a, b.stats_a, b.stats_b, b.rounds_a, fb, fa),
                                                  (b.b, 1 - b.score_a, b.stats_b, b.stats_a, b.rounds_b, fa, fb)):
            state.hist[me].append(dict(
                date=d, minutes=mins, score=sc, cat=cat if sc != 0.5 else "OTHER", has_stats=has, wc=wc,
                **{"for": sa, "against": sb}, rounds_for=ra,
                fac_for={s: _factor(state, opp_f, s, "against") for s in ADJ},     # opponent's tendency to concede
                fac_against={s: _factor(state, opp_f, s, "for") for s in ADJ},     # opponent's tendency to produce
                opp_q={k: opp_f[k] for k in ("sig_def", "sig_acc", "td_def", "td_acc", "elo")}))
        if has:
            for stat in set(RATE) | {"sig_a", "td_a", "head_l", "body_l", "leg_l", "dist_l", "clinch_l", "ground_l"}:
                if b.stats_a.get(stat) is not None:
                    state.glob.setdefault(stat, [0.0, 0.0])
                    state.glob[stat][0] += b.stats_a[stat] + (b.stats_b.get(stat) or 0)
                    state.glob[stat][1] += 2 * mins
        ea = 1 / (1 + 10 ** ((state.elo[b.b] - state.elo[b.a]) / 400))
        upd[b.a] += ELO_K * (b.score_a - ea)
        upd[b.b] += ELO_K * ((1 - b.score_a) - (1 - ea))
        if b.ref:
            fin = float(cat in ("KO", "SUB"))
            state.ref[b.ref][0] += 1
            state.ref[b.ref][1] += fin
            state.ref_glob[0] += 1
            state.ref_glob[1] += fin
    for fid, delta in upd.items():
        state.elo[fid] += delta
    done = [b for b in event if b.score_a is not None]
    if done:
        state.elo2.update_event([(b.a, b.b, b.score_a, _cat(b.method), b.stats_a.get("sig_l"), b.stats_b.get("sig_l")) for b in done],
                                date.fromisoformat(done[0].date))


def build_features(raw: list[RawBout], statics: dict, return_state: bool = False):
    ordered = sorted(raw, key=lambda x: (x.date, x.event_id, x.order))
    state = State()
    rows = []
    i = 0
    while i < len(ordered):
        j = i
        while j < len(ordered) and (ordered[j].date, ordered[j].event_id) == (ordered[i].date, ordered[i].event_id):
            j += 1
        event = ordered[i:j]
        d = date.fromisoformat(event[0].date)
        by_id = {}
        for b in event:
            r = bout_row(state, b, d, statics)
            r.update(bout_id=b.bout_id, date=b.date, event_id=b.event_id, y=b.score_a, odds_a=b.odds_a, odds_b=b.odds_b,
                     a=b.a, b=b.b, wc=b.wc, method=b.method, end_round=b.end_round, fight_sec=b.fight_sec,
                     sched=b.sched, ref=b.ref, sig_obs_a=b.stats_a.get("sig_l"), sig_obs_b=b.stats_b.get("sig_l"),
                     td_obs_a=b.stats_a.get("td_l"), td_obs_b=b.stats_b.get("td_l"), kd_obs_a=b.stats_a.get("kd"), kd_obs_b=b.stats_b.get("kd"))
            by_id[b.bout_id] = r
        _update(state, event, by_id)
        rows.extend(by_id.values())
        i = j
    from ufcmodel.features.joint import add_joint_features
    add_joint_features(rows, ordered)
    return (rows, state) if return_state else rows
