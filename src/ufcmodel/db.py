"""DuckDB schema for Phase 1. `tags` is added in Phase 6, once its schema is fixed."""
from pathlib import Path

import duckdb

# Per-fighter counting stats shared by `rounds` and `bout_totals`.
STAT_COLS = [
    "kd",
    "sig_l", "sig_a",
    "head_l", "head_a", "body_l", "body_a", "leg_l", "leg_a",
    "dist_l", "dist_a", "clinch_l", "clinch_a", "ground_l", "ground_a",
    "total_l", "total_a",
    "td_l", "td_a",
    "sub_att", "rev", "ctrl_sec",
]
_stats_ddl = ",\n  ".join(f"{c} INTEGER" for c in STAT_COLS)

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS events (
  event_id VARCHAR PRIMARY KEY, name VARCHAR, date DATE,
  city VARCHAR, country VARCHAR, venue VARCHAR
);
CREATE TABLE IF NOT EXISTS fighters (
  fighter_id VARCHAR PRIMARY KEY, name VARCHAR, dob DATE,
  height_cm DOUBLE, reach_cm DOUBLE, stance VARCHAR
);
CREATE TABLE IF NOT EXISTS fighter_aliases (
  alias VARCHAR, fighter_id VARCHAR, source VARCHAR
);
CREATE TABLE IF NOT EXISTS bouts (
  bout_id VARCHAR PRIMARY KEY, event_id VARCHAR, weight_class VARCHAR,
  is_title BOOLEAN, scheduled_rounds INTEGER, method VARCHAR, method_detail VARCHAR,
  end_round INTEGER, end_time_sec INTEGER, referee VARCHAR, card_position INTEGER,
  round_lengths VARCHAR, fight_seconds INTEGER  -- round_lengths: '5,5,5'; fight_seconds: time actually fought
);
CREATE TABLE IF NOT EXISTS bout_fighter (
  bout_id VARCHAR, fighter_id VARCHAR, corner VARCHAR, result VARCHAR
);
CREATE TABLE IF NOT EXISTS rounds (
  bout_id VARCHAR, fighter_id VARCHAR, round INTEGER,
  {_stats_ddl}
);
CREATE TABLE IF NOT EXISTS bout_totals (
  bout_id VARCHAR, fighter_id VARCHAR,
  {_stats_ddl}
);
CREATE TABLE IF NOT EXISTS scorecards (
  bout_id VARCHAR, judge VARCHAR, round INTEGER, fighter_id VARCHAR, score INTEGER
);
CREATE TABLE IF NOT EXISTS odds_snapshots (
  bout_id VARCHAR, bookmaker VARCHAR, ts TIMESTAMP, fighter_id VARCHAR,
  price_decimal DOUBLE, kind VARCHAR  -- 'opening' | 'closing' | 'intermediate'
);
CREATE TABLE IF NOT EXISTS context (
  event_id VARCHAR, bout_id VARCHAR, altitude_m DOUBLE, cage_ft DOUBLE,
  missed_weight_fighter_id VARCHAR, days_notice INTEGER
);
CREATE TABLE IF NOT EXISTS background (
  fighter_id VARCHAR, as_of DATE, fact_type VARCHAR, value VARCHAR
);
CREATE TABLE IF NOT EXISTS tags (
  bout_id VARCHAR, tagger VARCHAR, pass_no INTEGER, round INTEGER, t_sec DOUBLE,
  event_type VARCHAR, fighter VARCHAR, fields VARCHAR  -- fields: JSON object of the event's other values
);
"""

TABLES = [
    "events", "fighters", "fighter_aliases", "bouts", "bout_fighter", "rounds",
    "bout_totals", "scorecards", "odds_snapshots", "context", "background", "tags",
]


def connect(path: str | Path) -> duckdb.DuckDBPyConnection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA)
    return con
