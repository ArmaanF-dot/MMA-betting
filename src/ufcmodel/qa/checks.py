"""Phase 1 data quality checks. Each check returns the offending rows; hard failures block the build."""
from dataclasses import dataclass

from ufcmodel.db import STAT_COLS


@dataclass
class Result:
    name: str
    severity: str  # 'hard' | 'warn'
    rows: list

    @property
    def failed(self) -> bool:
        return bool(self.rows)


def run_checks(con, round_seconds: int = 300, overround=(1.02, 1.10)) -> list[Result]:
    q = lambda sql: con.execute(sql).fetchall()
    out: list[Result] = []

    sums = ", ".join(f"sum(r.{c}) AS {c}" for c in STAT_COLS)
    diffs = " OR ".join(f"(t.{c} IS NOT NULL AND s.{c} IS DISTINCT FROM t.{c})" for c in STAT_COLS)  # an unknown total is not a mismatch
    out.append(Result("round_stats_sum_to_bout_totals", "hard", q(f"""
        SELECT t.bout_id, t.fighter_id FROM bout_totals t
        JOIN (SELECT bout_id, fighter_id, {sums} FROM rounds r GROUP BY 1, 2) s
          USING (bout_id, fighter_id)
        WHERE {diffs}""")))

    pairs = [("sig", "sig"), ("head", "head"), ("body", "body"), ("leg", "leg"),
             ("dist", "dist"), ("clinch", "clinch"), ("ground", "ground"),
             ("total", "total"), ("td", "td")]
    cond = " OR ".join(f"{p}_l > {p}_a" for p, _ in pairs)
    for tbl in ("rounds", "bout_totals"):
        out.append(Result(f"landed_le_attempted[{tbl}]", "hard",
                          q(f"SELECT bout_id, fighter_id FROM {tbl} WHERE {cond}")))

    out.append(Result("control_time_le_round_length", "hard", q(f"""
        SELECT r.bout_id, r.fighter_id, r.round FROM rounds r JOIN bouts b USING (bout_id)
        WHERE r.ctrl_sec > CASE WHEN r.round = b.end_round AND b.end_time_sec IS NOT NULL
                                THEN b.end_time_sec
                                ELSE coalesce(try_cast(string_split(b.round_lengths, ',')[r.round] AS INTEGER) * 60,
                                              {round_seconds}) END""")))

    out.append(Result("sig_strikes_by_target_equal_by_position", "hard", q("""
        SELECT bout_id, fighter_id, round FROM rounds
        WHERE head_l + body_l + leg_l <> dist_l + clinch_l + ground_l
           OR head_l + body_l + leg_l <> sig_l""")))

    out.append(Result("bout_has_two_fighters_one_result", "hard", q("""
        SELECT b.bout_id FROM bouts b LEFT JOIN bout_fighter f USING (bout_id)
        GROUP BY b.bout_id
        HAVING count(f.fighter_id) <> 2 OR count(DISTINCT f.fighter_id) <> 2
            OR count(DISTINCT f.corner) <> 2
            OR sum(CASE WHEN f.result = 'win' THEN 1 ELSE 0 END) > 1
            OR count(f.result) <> 2""")))

    out.append(Result("no_duplicate_events", "hard", q("""
        SELECT name, date FROM events GROUP BY 1, 2 HAVING count(*) > 1""")))
    # Same pair twice in one event. A fighter may appear several times (one-night tournaments); a no-contest restart is fine.
    out.append(Result("no_duplicate_bouts", "hard", q("""
        SELECT event_id, a, b FROM (
          SELECT b.event_id, b.bout_id, min(f.fighter_id) AS a, max(f.fighter_id) AS b
          FROM bouts b JOIN bout_fighter f USING (bout_id)
          WHERE coalesce(b.method, '') <> 'No Contest' GROUP BY 1, 2)  -- a no-contest can be restarted the same night
        GROUP BY 1, 2, 3 HAVING count(*) > 1""")))

    lo, hi = overround
    out.append(Result("odds_overround_plausible", "warn", q(f"""
        SELECT bout_id, bookmaker, ts, kind, sum(1 / price_decimal) AS overround
        FROM odds_snapshots GROUP BY 1, 2, 3, 4
        HAVING count(*) = 2 AND (sum(1 / price_decimal) < {lo} OR sum(1 / price_decimal) > {hi})""")))
    return out


def report(results: list[Result]) -> tuple[str, int]:
    lines, hard = [], 0
    for r in results:
        status = "ok" if not r.failed else ("FAIL" if r.severity == "hard" else "warn")
        lines.append(f"[{status:4}] {r.name}" + (f"  ({len(r.rows)} rows)" if r.failed else ""))
        if r.failed and r.severity == "hard":
            hard += 1
    lines.append(f"hard failures: {hard}")
    return "\n".join(lines), hard
