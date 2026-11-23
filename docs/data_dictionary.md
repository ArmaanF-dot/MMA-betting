# Data dictionary

Source files (local only, never redistributed): `data/raw/greco/` (Greco1899/scrape_ufc_stats CSVs of UFCStats data, GPL-3.0
repository) and `data/raw/ufc_dataset/odds_raw.csv` (jansen88/ufc-data, betmma.tips odds). `python -m ufcmodel convert` writes the
per-table CSVs in `data/raw/csv/`; `python -m ufcmodel load data/raw/csv` loads them into `data/processed/ufc.duckdb`.

| Table | Rows | Notes |
|---|---|---|
| `events` | one per event | `event_id` is the UFCStats event hash; city and country split from the location text; `venue` is blank (not in the source) |
| `fighters` | one per fighter | `fighter_id` is the UFCStats fighter hash. Nine names appear twice in the source and are merged into `x-<name>` with blank DOB, height and reach |
| `fighter_aliases` | name variants | sources: `ufcstats`, `betmma` (exact match), `betmma_fuzzy` (both names at least 0.88 similar) |
| `bouts` | one per bout | `method` is Decision, KO/TKO (doctor's stoppages included), Submission, DQ, Could Not Continue, No Contest or Other; `method_detail` is the finish or the decision type; `round_lengths` like `5,5,5`; `fight_seconds` is time actually fought; `card_position` 1 is the main event |
| `bout_fighter` | two per bout | `corner` is assigned from a hash of the bout id, because the source lists the winner (or the favourite) first and that order must not leak; `result` is win, loss, draw or nc |
| `rounds` | one per fighter per round | every UFCStats column: knockdowns, significant strikes by target (head, body, leg) and position (distance, clinch, ground), total strikes, takedowns, submission attempts, reversals, control seconds. NULL means the source had a dash |
| `bout_totals` | one per fighter per bout | sum of the rounds; NULL if any round was missing that stat |
| `odds_snapshots` | two per odds pair | one decimal-odds pair per bout, no timestamp, `kind = 'unknown'` (not labelled opening or closing); 2014 to 2023-09 |
| `scorecards` | empty | UFCStats gives only per-fight scorecard totals inside a text field, not per round, so it is not loaded |
| `context`, `background` | empty | to be filled by Armaan (camp changes, injuries, credentials, missed weight, notice, cage size) |
| `tags` | tagger exports | `fields` is a JSON object of the event's other values; `pass_no` 2 is the re-tag used for kappa |
| `predictions`, `predictions_ml` | model outputs | written by the backtest and `phase10` runs |

Quality checks (`python -m ufcmodel qa`): rounds sum to totals, landed never exceeds attempted, control time within round length,
significant strikes by target equal by position and equal to the total, two fighters and at most one winner per bout, no duplicate
events or bouts (a no-contest restart the same night is allowed), odds overround warning (1.02 to 1.10).

Features (`src/ufcmodel/features/asof.py`): every value is computed from events strictly before the bout; `tests/test_asof.py`
rebuilds features after deleting later data and asserts they are identical.
