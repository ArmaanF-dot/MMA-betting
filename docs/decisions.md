# Decision log

## Phase 1 plan (2026-10-27)
- DuckDB schema for every Phase 1 table except `tags` (Phase 6). See `src/ufcmodel/db.py`.
- Source-agnostic ingest: one CSV per table in `data/raw/csv/`, loaded by `python -m ufcmodel load`.
- Seven hard QA checks plus an odds-overround warning, in `src/ufcmodel/qa/checks.py`, unit-tested.
- Live fetching goes through `ingest/fetch.py`: raw-HTML cache, 3 s rate limit, robots.txt check.

## Phase 1 results note (partial)
- Works: schema, CSV loader, QA checks, fetch client. 15 tests pass.
- **Blocked: UFCStats ingest.** `ufcstats.com` has no robots.txt, but it answers requests with a
  JavaScript proof-of-work "Checking your browser" page instead of data. Solving that would be
  bypassing bot detection, which breaks principle 7 (respect site terms), so the fetch client raises
  `BlockedError` instead. No scraper/parsers were written because there is no real HTML to test them on.
- **Not done:** full history ingest, entity resolution / alias table, `make update`, odds, scorecards.
  Phase 1 acceptance is therefore NOT met and Phase 2 has not started.

## Dataset check: `data/raw/ufc_dataset/` (jansen88/ufc-data, 2026-10-27)
Inspected, not yet converted. 7,340 bouts, 1994-03-11 to 2023-09-16; 4,106 fighters; odds on 3,502 bouts (2014-11-07 on).
- **Has:** event date/name/location, weight class, both fighters' names, outcome, method, round, time, fight-level
  Kd/Str/Td/Sub, one decimal odds pair per bout, height/reach/stance/DOB.
- **Missing vs spec:** per-round stats, strikes by target and position, control time, reversals, referee, scorecards,
  UFCStats fighter IDs, opening vs closing odds with timestamps, bookmaker. So Phases 4.2-4.6 and 5 on public data,
  the round-stats QA checks and the judging model cannot be built from it.
- **Leakage risk:** fighter career stats (SLpM, Str.Acc., TDAvg., etc.) were scraped once in Sept 2023, so they include
  the fighter's later fights. They must NOT be used as as-of features; only static fields (height, reach, DOB, stance) are safe.
- **Stale:** nothing after 2023-09-16, so about three years of fights are missing.
- No licence is stated in the README; keep it local, never redistribute.
- Usable now: results, methods, dates, odds from 2014, static physicals. Enough for Elo/Glicko (B1) and a de-vigged-odds
  benchmark (B0) on 2014-2023. Not enough to satisfy Phase 1 acceptance as written.

## Options to unblock (Armaan's call)
1. Download a UFCStats-derived dataset yourself in a normal browser (e.g. a Kaggle UFC dataset; check its
   licence), put the files in `data/raw/`, and a converter to the per-table CSVs gets written.
2. Ask UFCStats for permission or an allowed access route.
3. Use another source with acceptable terms (Sherdog, Tapology, a paid feed). Paid data needs your approval.

## Phase 1 / Phase 3 results note (2026-10-27, jansen88/ufc-data download)
Run: `python -m ufcmodel convert && python -m ufcmodel load data/raw/csv && python -m ufcmodel qa && python -m ufcmodel backtest`.
38 tests pass. QA: 0 hard failures, 1 warning (odds overround, below).

**What was built**
- Converter to the per-table CSVs (events, fighters, aliases, bouts, bout_fighter, bout_totals, odds_snapshots).
  7,339 bouts, 663 events, 4,100 fighters. Career-average fighter stats are deliberately not carried over (leakage).
- B0 de-vigged odds (multiplicative, power, Shin) and B1 Elo, walk-forward, with log loss, Brier, accuracy, AUC, ECE,
  reliability deciles, paired-bootstrap gaps and segment splits. Report: `docs/phase3_baseline_report.md`.

**Result** (3,368 bouts with odds, 2014-11 to 2022-09-16, draws/NC excluded)
- Market log loss 0.6187 (power), coin flip 0.6931, Elo 0.6827.
- Elo minus market: +0.064 [+0.053, +0.075] log loss (95% paired bootstrap). The market is far better, as the spec expects at this stage.
- Elo minus coin flip: -0.010 [-0.018, -0.003]. Elo is only slightly better than chance.
- Elo K is tuned per year on earlier bouts only. First grid topped out at 64 for every year, so the grid was widened to
  8-256; chosen values are now 64-96 (interior). Elo sits near coin-flip level; recency decay and debut handling would be the next tests.
- Default benchmark by lowest ECE is B0 power, but the three de-vig methods differ by about 0.0001 log loss, so the choice does not matter here.

**Gaps and data caveats (logged, not fixed)**
- Odds have no opening/closing label, bookmaker or timestamp. Median implied-probability sum is about 1.01 and about 85% of pairs
  sit outside the spec's 1.02-1.10 range, so these are not one bookmaker's prices (likely averaged or best-of). Treated as a
  closing-odds stand-in only; closing-line value cannot be measured. `odds_overround_plausible` stays as a warning.
- The source writes missing odds as `inf`; 102 such rows are rejected.
- Odds matching: 3,651 exact, 243 fuzzy (both names >= 0.88 similarity, alias source `betmma_fuzzy`), 456 unmatched
  (`data/interim/odds_unmatched.csv`; 108 are Oct-Dec 2023 events absent from the bout file (119 after the data end date)). One matched row names a winner that disagrees with the result.
- Six duplicate fighter names (Bruno Silva, Jean Silva, Joey Gomez, Michael McDonald, Mike Davis, Tony Johnson) cannot be told
  apart because bouts carry names only; each is merged into one fighter with DOB, height and reach left blank.
- No UFCStats fighter IDs; fighter_id is a name slug.
- The source lists the winner as fighter1, so red/blue corner is assigned from a hash of the bout id. Using list order would leak the result.
- `no_duplicate_bouts` was changed to compare fighter pairs within an event. The original per-fighter version wrongly flagged
  1994-1999 one-night tournaments, where a fighter fights several times.
- bout_totals has only knockdowns, significant strikes landed, takedowns landed and submission attempts, and NULL where the source has `--`.
  There is no per-round data, so the round-stats QA checks have nothing to test.
- Last 12 months of data (from 2022-09-17) are a locked holdout: not predicted or scored here.
- Elo only; Glicko-2 not built. B2/B3 not built because honest as-of features are not available from this dataset.
- Segments unavailable: main card vs prelims, five vs three rounds, tagged vs untagged.

**Status:** Phase 1 acceptance is still NOT met (no per-round history, no full alias resolution, no `make update`, data ends 2023-09-16).
Phase 3 is partial (B0 and B1 only). Phase 2 has not started.

## Phases 2, 3 (B2/B3), 6, 9, 10, 11 results note (2026-10-27, same dataset)
Free tools only (scikit-learn, LightGBM, NumPy). No paid data, no scraping of any blocked source.

**Built**
- Phase 2, public-data subset: as-of feature store (`features/asof.py`): Elo, recency-weighted (24 month half-life) and shrunk record,
  finish-method rates, experience, activity, age, physicals, stance, per-15-minute strike/takedown/knockdown/submission rates
  shrunk to the as-of global rate. Leakage test rebuilds features after deleting all later data (synthetic and real data); a
  swap test checks the A-minus-B features flip sign. Models train on both corner orders and average, so P(A)+P(B)=1.
- Phase 3: B2 logistic and B3 LightGBM, walk-forward by year with inner validation for window (2005/2010/2014) and C.
- Phase 9: stacking (logistic on the component log-odds, fit on earlier folds only) and market blend with w chosen on earlier folds.
- Phase 10: segments, paired-bootstrap gaps, reliability, full-model ablation, plain-text drivers, locked holdout scored once.
- Phase 11 (code only): fractional-Kelly betting simulation, paper-trade log, grading and gate (`betting/paper.py`).
- Phase 6: `tools/tagger.html`, `tags` table, importer, Cohen's kappa per field, takedown cross-check, `docs/tagging_guide.md`.
- Fight-week HTML report generator (`python -m ufcmodel fightweek CARD.csv`), demo in `docs/fightweek.html`.

**Results** (details in `docs/phase10_evaluation.md` and `docs/phase10_holdout.md`)
- Development folds 2015 to 2022-09-16, 3,683 decisive bouts: log loss coin 0.693, Elo 0.683, B2 0.662, B3 0.662. B2/B3 beat Elo by
  about 0.021 (95% interval excludes 0).
- Bouts with odds, 2017 on (n = 2,394): market 0.613; stack without market 0.663 (gap +0.050 [+0.038, +0.062]); blend with market
  0.615 (gap +0.002 [-0.001, +0.004]). The market is far better than the model; the blend only matches it.
- Ablation (full model): kept elo, age_growth, physical, striking; dropped record, experience, activity, grappling, context (their
  intervals include zero). The models were then pruned to the kept groups, which changed log loss by under 0.001, so the pruned numbers
  are the ones above. The pruning used the same folds, so it is slightly optimistic.
- Locked holdout (2022-09-17 to 2023-09-16, scored once): B2 0.648, B3 0.652, stack 0.649, market 0.612 and blend 0.612 on 452
  bouts with odds; blend minus market -0.0003 [-0.0031, +0.0024]. No edge over the market.
- Betting simulation (stand-in odds, upper bound): 417 bets, flat ROI -4.9% [-19.1%, +9.9%]. No evidence of a profitable edge.

**Gaps (cannot be closed with free, permitted data)**
- Phase 4 skills, Phase 5 styles and archetypes, Phase 8 simulator and judging model, method and round probabilities: need per-round,
  positional or tagged data. Only the tagging route (yours) can supply the tagged parts; UFCStats round data is behind a bot check.
- Phase 2 opponent adjustment (hierarchical NegBin) and half-life tuning not done; the fixed 24 months and K=64 stand in.
- Phase 7 context: cage size, altitude, missed weight, notice, referee, judges, travel are not in the data. Age, reach, stance,
  layoff and weight-class moves are in (group "context" and others) and mostly dropped by ablation.
- LightGBM monotone constraints, beta/isotonic calibration (the stack acts as a Platt-style recalibration), the disagreement model
  and bootstrap-across-members uncertainty are not built. Coverage flags and low-confidence handling are.
- Closing-line value, decision-time odds and a live paper-trading period are impossible with this odds file (no timestamps, no
  opening/closing label) and no events after 2023-09-16. The Phase 11 gate is not passed and was not attempted.
- No GitHub Actions weekly update: there is no permitted live event source yet.

**Status:** everything the data allows is built and the full pipeline reruns from commands. The headline finding is negative on
this data: no model or blend beats de-vigged odds. More free public history (per-round stats) is the main thing that could change
that, and it needs a source with acceptable terms.

## Round 3 (2026-10-27): per-round data, Phases 4, 5, 7, 8, 9, 10 rebuilt. SUPERSEDES the "same dataset" note above

**Data.** Greco1899/scrape_ufc_stats CSVs (UFCStats data, public GitHub repository, GPL-3.0; the data is UFCStats's, so it stays local
and is never redistributed). 8,962 bouts, 794 events, 1994-03-11 to 2026-10-24, 42,058 round rows: strikes by target and position,
control time, referee, method, round lengths. Odds are still the older betmma.tips file (single pair per bout, no timestamp or
open/close label, 2014 to 2023-09): 3,929 matched (3,674 exact, 255 fuzzy). `python -m ufcmodel update` refreshes the files; the
weekly workflow (`.github/workflows/weekly.yml`) is written but not run. Phase 1 acceptance: full history ingested, 0 hard QA
failures, one-command update. Bugs found and fixed on the way: counts arrive as "1.0" (parser), a no-contest restart is not a
duplicate bout, an unknown total is not a mismatch, early UFC rounds were up to 20 minutes (round lengths now stored).
The previous holdout (2022-09-17 to 2023-09-16) was scored in round 2, so it is now ordinary development data; the new holdout is the
last 12 months (2025-10-25 to 2026-10-24), scored once.

**Built.** As-of feature store on rounds (opponent-adjusted skills with uncertainty, durability, cardio, trend, style axes, matchup
interactions, referee tendency, altitude), leakage tested on synthetic and real data; skills evaluated (`docs/phase4_skills.md`);
style archetypes with stability (`docs/phase5_styles.md`) and a label template for you (`docs/style_labels_template.csv`); judging model
and round-level simulator with calibrated finish hazards (`docs/phase8_simulator.md`); direct method/round models; stack with the
simulator as M4; monotone-constrained LightGBM; calibration check; disagreement model; ablation and greedy group selection
(`config/feature_groups.json`); betting simulation and paper-trade gate code; tagger, tag import and kappa; fight-week report with
method, round and style sections (`docs/fightweek.html`, a demo on the latest card).

**Results** (details in the docs named above)
- Phase 4: skill components beat a division-average model on held-out fighter-fights: strikes landed -3.01 deviance [-3.38, -2.65],
  takedowns -0.36 [-0.40, -0.32], knockdowns (power x chin per head strike) -0.015 [-0.022, -0.007]. The per-15-minute knockdown
  rate version did not (+0.033), so it is not used.
- Win probability, 2015 to 2025-10-24 (n = 5,256): coin 0.693, Elo 0.682, B2 0.652, B3 0.654, simulator about 0.67.
- With odds, 2017 to 2023-09 (n = 2,884): market 0.613; stack without market 0.656 (+0.043 [+0.033, +0.053]); blend with market
  0.614 (+0.001 [-0.001, +0.004]). The model does not beat the market and the blend only matches it.
- Feature groups: greedy selection kept style_interactions, age_growth and record; experience was the next candidate and missed (change
  [-0.0037, +0.0003]). The single-group ablation was inconclusive for most groups because they overlap; both tables are in the report.
  The style matrix and axes did not earn a place; the three interaction terms did.
- Simulator vs direct models: win probability 0.67 vs 0.65 (worse, but better than Elo); 6-class winner x method 1.64 vs 1.60 direct vs
  1.72 base rates; round of finish 1.213 vs 1.205 direct vs 1.225 base rates; strike totals 80% coverage with mean ratio 0.99.
  Acceptance ("competitive with the direct models") is only partly met.
- Calibration: recalibrating the stack (Platt, beta, isotonic) made it slightly worse, so the raw stack is used.
- Disagreement model: walk-forward AUC 0.57 [0.55, 0.59], a small signal; even its top quintile of bouts had the stack worse than the market
  (+0.025 log loss), so it does not rescue a betting edge.
- Betting simulation on the stand-in odds: 555 bets, flat ROI -3.3% [-16.5%, +11.0%].
- Locked holdout, scored once (552 decisive bouts, no odds exist for it): B2 0.637, B3 0.632, stack 0.636, simulator 0.662, Elo 0.688,
  coin 0.693. Models clearly beat Elo and chance; there is no market comparison.

**Gaps that remain**
- Phase 8: a per-round positional semi-Markov model needs tagged position sequences (yours). The simulator is round-level. No per-round
  judge scores exist, so 10-8 rounds and judge tendencies are not modelled.
- Phase 4: no PyMC hierarchical fit; recency-weighted, opponent-adjusted, shrunk rates with uncertainty stand in. Get-up, cage vs open-mat
  takedowns, leg-kick attrition across rounds and the camp/coach covariates need tags or your background table.
- Phase 5: naming clusters and the semi-supervised placement need your labels; tag-only axes and the habits catalogue need tags.
- Phase 7: cage size, missed weight, days of notice, judges and travel are not in the data; `context` and `background` tables are for you.
- Phase 11: no real decision-time or closing odds, so closing-line value, and therefore the gate and a live paper-trading period, cannot
  start. The paper log, grading and gate code are tested and ready.
- Half-life and Elo K are fixed (24 months, 64), not tuned. The three odds-based comparisons are bounded by odds quality.
- Greedy selection and ablation used the development folds, so their gains are slightly optimistic; the one-time holdout is the check.

## Round 4 (2026-10-27): stat padding and opponent quality

Prompted by Murzakanov (unbeaten against mid-pack opponents rated 1506-1606, Elo 1680 above Costa's 1631, then lost to Costa and
Reyes). Four improvements, each tested walk-forward on the development folds (2015 to 2025-10-24, 5,256 decisive bouts); the locked
holdout was already scored once and was not re-used. Details: `docs/improvements_test.md`.

- **Opponent-adjusted accuracy and defence** (log-odds correction for the defence or accuracy of the opponents faced). Diagnosis
  confirmed padding: fighters who had faced strong defenders were predicted 44.0% accurate and landed 45.4%. As a model feature it
  showed no clear gain on its own (-0.0006 [-0.0020, +0.0008]) and was not picked: the joint fit carries the same information.
- **Elo2** (margin of victory and a Glicko-style rating deviation, tuned on pre-2015 bouts only: K 48, full margin weight, layoff
  inflation 40). Alone it beats Elo (0.6781 vs 0.6819, difference -0.0038 [-0.0065, -0.0011]). Kept.
- **Joint offence/defence fit** (Poisson model of every fighter's offence and every opponent's defence estimated together, refit
  monthly on earlier fights only, for strikes, takedowns and control). Biggest single gain; first group picked. Kept.
- **Quality of opposition** (quality-weighted win rate, record vs opponents rated 1600+, best win, schedule strength, untested flag).
  Helped on its own (-0.0027 [-0.0052, -0.0003] logistic) but not picked once the joint fit and Elo2 were in.
- Greedy selection with every group available now keeps **joint_adj, age_growth, elo2** (was style_interactions, age_growth, record).
- Result: logistic 0.6519 to 0.6484 on all development bouts; on bouts with odds the stack went from 0.6558 to 0.6525 and its gap to the
  market from +0.043 to +0.040 log loss. The market blend still only matches the market (+0.0016 [-0.0008, +0.0041]); betting
  simulation -3.7% [-15.6%, +9.5%]. Genuine but small improvement; no edge over the market.
- Murzakanov with the new model: 51% vs Costa (lost), 46% vs Reyes (lost). His opponents were mid-pack rather than weak, so the
  adjustment moves him only a little.
- Tests added: Elo2 behaviour and the joint fit's recovery and as-of behaviour; leakage and corner-swap tests cover the new features.

## Round 5 (2026-10-27): softer selection, age x style, finish recalibration, model-router mod

Tests: `docs/softer_selection_test.md` and `docs/finish_recalibration_test.md`; full re-evaluation in `docs/phase10_evaluation.md`,
`docs/phase8_simulator.md`, `docs/replay_last_10.md`. Development folds only.

- **Softer selection adopted.** Groups were chosen on 2015-2021 only and scored on 2022 to 2025-10 (1,947 bouts). All 19 groups with a strong
  ridge penalty (C grid 0.001-0.03) beat the 3-group hard-rule set: 0.6338 vs 0.6410, difference -0.0072 [-0.0135, -0.0011]. A relaxed
  greedy (7 groups, no interval rule) and all-groups LightGBM showed no clear difference. `config/feature_groups.json` now keeps all groups.
- **Age x style curves** (six features: age against control game, power, distance striking, head damage, KO losses, weight class)
  alone made no clear difference (-0.0002 [-0.0022, +0.0018]); they are inside the all-groups model, not a separate decision.
- **Finish recalibration adopted:** calibrate on the last 150 bouts and multiply the finish scalars per division (shrunk to the global level
  with 20 pseudo-bouts). Round-of-finish and goes-the-distance log loss both improved with intervals below zero (-0.0077 and -0.0103);
  distance ECE 0.023 to 0.014; expected vs actual distance rate 50.3% vs 50.4%. Calibrating on only the last 150 bouts without division
  multipliers was worse.
- **Result.** Logistic 0.6484 to 0.6430 on all development bouts (5,256); on bouts with odds the stack's gap to the market narrowed from
  +0.0398 to +0.0345 [+0.0243, +0.0445]. Blend with market vs market +0.0014 [-0.0015, +0.0043]: a tie. Simulator: winner x method 1.6408 to
  1.6322, round of finish 1.2139 to 1.2045 (now level with the direct model's 1.2049), goes-the-distance 0.6825 to 0.6711; strike-total
  coverage 80%, mean ratio 1.00. Betting simulation on the stand-in odds: 1,193 bets, flat -5.0% [-13.1%, +2.9%]. Disagreement model's top
  quintile: stack minus market +0.006 (still not better than the market).
- **Recent events.** The last 10 events (129 bouts) replayed with only earlier data: 60.5% of winners right, log loss 0.670 (coin 0.693, Elo
  0.706). Fights going the distance: 33% actual vs 43% expected, unchanged by the recalibration: the long calibration window is
  diluting a recent rise in finishes, or it is chance (about 2.4 standard errors). Watch it on the next cards; a recency-weighted
  drift term is the next thing to test if it persists.
- **Holdout.** The locked holdout (2025-10-25 to 2026-10-24) was scored once, with the model as it stood in round 3. Every change since
  (rounds 4 and 5) was chosen on development folds, and the holdout was not re-scored, so it no longer tests the current model. The
  honest out-of-sample test from here is forward: each new card, logged before the event, graded after.
- **model-router mod** (`~/.claude/dev-mods/.../model-router`): routes subagents to Haiku/Sonnet/Opus by task and gives the model a
  `delegate` tool that runs mechanical read-only work on a cheaper model. Live test found and fixed a real bug: a registered tool must
  answer with a string or array, not an object (the mocked tests could not catch it). Live: Haiku summary of a known file was correct on
  every figure; Sonnet classification correct; missing-file error clear. `/router` shows the counts.


## Round 6 (2026-10-27): real odds backfill and finish-drift test

**Odds backfill (plan 1a): done.** `ufcmodel/ingest/bfo.py` reads Best Fight Odds event pages (robots.txt allows /events/, terms have no scraping clause; one page at a time, 4 s pause; raw pages kept gzipped under data/raw/bfo, local only). 1,704 bouts from 2023-06 to UFC 333 now have closing prices from up to 9 books in the new table `odds_books` (kept apart from `odds_snapshots`, which the feature store reads as one price per fighter). Median bookmaker margin 4.0% to 5.5% (Kalshi 3.2%, Polymarket 1.0%). Agrees with the old file on 246 overlapping bouts (mean difference +0.0001 in win probability, mean absolute 0.010). Bug fixed on the way: price cells carry a line-movement arrow that broke the parser (154 bouts instead of 1,704).

**Model against real prices (plan 1c), development period only (1,150 bouts with 3+ books, 2023-06 to 2025-10-18):** market log loss 0.5889, stack 0.6236, logistic 0.6252. Stack minus market +0.0347 [+0.0184, +0.0502]; a fixed 50/50 blend is still +0.0069 [-0.0010, +0.0146]. GBP 10 flat on the model's pick returns -5.4% (stack) and -5.8% (logistic) at the median price; at the best price at any book +0.4% and -2.6%, all intervals include zero. Value-only rules (edge above 0, 5, 10%) return -6% to -13% at the median price and -0.1% to -6.7% at the best price. The earlier +4.9% on the old file came from its near-zero margin (mean implied-probability sum 1.006) and is withdrawn. No real-money case.

**Finish-drift test (plan 2a): nothing adopted.** Recency-weighted division finish multipliers (half-life 730, 365, 365 with 2400 bouts, 180 with 2400 bouts) against the current equal-weight last 1,200 bouts, development folds 2015 to 2025-10-24. No variant improved round-of-finish or goes-the-distance log loss (differences +0.0008 to +0.0055; the 180-day variant is clearly worse). In the last dev fold (2025) the simulator already over-predicts the distance rate (53.1% vs 50.6%) and shorter half-lives make it worse (up to 55.1%). So the dev years show no drift to chase. The 33% vs 45% gap seen in the last 20 events sits mostly in 2026, which is the locked holdout period: it cannot be tuned on. Left as is; the forward cards are the test. If the gap persists over the next ~10 cards, revisit with a drift term fitted on data that is then out of sample.


## Round 7 (2026-10-27): prop markets and two-fight parlays against real prices (development period only)

Prop prices (goes to decision; fighter wins inside the distance) read from the cached Best Fight Odds pages into `odds_props` (`scripts/load_props.py`). Model probabilities are walk-forward for the 2023, 2024 and 2025 folds (`scripts/prop_model.py`); test in `scripts/prop_test.py`, sportsbooks only (Polymarket and Kalshi excluded), thresholds fixed in advance.

- **Goes the distance** (1,109 fights with 3+ books): market log loss 0.6425; direct LightGBM 0.6565 (+0.0140 [+0.0005, +0.0274] vs market), simulator 0.6796 (+0.0371), 50/50 blend 0.6623 (+0.0198), base rate 0.6978. The market wins. Betting the blend model's side returns -1.8% to +1.4% at the median price and +4.2% to +7.0% at the best price, every interval including zero.
- **Fighter wins inside the distance** (1,962 fighter-markets, 1,008 fights, 2+ books): market 0.5001; blend 0.5231 (+0.0230 [+0.0107, +0.0349]). Betting the model returns -10.8% to -15.5% at the median price and -9% at the best price, intervals below zero. No edge.
- **Market bias, found after the fact (not adopted):** decisions happened 50.0% / 54.6% / 50.7% of the time in 2023 / 2024 / 2025 while the market's de-vigged average was 43.3% / 45.5% / 48.0%. A blind "goes to decision" bet returned +9.7% / +15.7% / -1.0% at the median price (+15.8% / +22.4% / +2.4% at the best price). The gap closed by 2025, and the last 20 events (2026, already reported: 33% decisions) point the other way, so this looks like a drifting regime rather than a stable edge. It was chosen after seeing the results, so it is only a hypothesis; it has not been tested on the 2026 holdout period and should not be.
- **Two-fight parlays** (one per event, 103 events, moneylines at the median price, product of the single prices): the two highest-edge model fights both won 8 times (8%), ROI -7.4% [-67%, +67%] (the same legs as two singles: -20.7%); the two shortest-priced favourites both won 74 times (72%), ROI +1.9% [-10.8%, +14.5%]. No parlay rule beat its singles in a way outside noise, and a parlay costs the margin on both legs.


## Round 8 (2026-10-27): wear and trend features (dropped)

Seven features added as a group `wear_trend`: strikes absorbed, takedown output and control time (last 3 fights against career), head strikes absorbed per 15 minutes over the last 3, KO losses in the last 3, days since the last KO loss, and the last-3 results trend against the career record. Walk-forward on the development folds 2015 to 2025-10-24 (`scripts/wear_test.py`, `docs/wear_trend_test.md`): logistic 0.6430 without, 0.6436 with (+0.0005 [-0.0003, +0.0013]); LightGBM 0.6465 without, 0.6451 with (-0.0013 [-0.0025, -0.0002]). The pre-set rule needed the logistic model to improve with an interval below zero; it did not, so the group was removed and the adopted model is unchanged. The small LightGBM gain is a hypothesis only: it is one model out of two, found by one look, and the effect is 0.1% of log loss.


## Round 9 (2026-10-27): short-notice flag (built, not adopted; to be re-run on the full crawl)

**Replacement detection** (`ingest/short_notice.py`): a fighter Y whose page lists a second, cancelled matchup on the same date shows that X (the opponent who fought) came in late if the X-Y matchup id is higher. On 641 cached fighter pages only 122 of 7,934 fighter-dates had a second opponent (1.5%), and 27 fights were flagged where both pages were read. Far below the real rate of late replacements, because the site keeps a cancelled matchup only if odds were posted and only on the original fighter's page. Too sparse to test; not used.

**Late-created matchups** (`scripts/late_matchup_test.py`, threshold fixed before looking: matchup id more than 150 above its event's median, about 2 to 3 weeks later than a typical card fight): 13.9% of 3,070 fights flagged. Late fights (n=420, 202 events): the favourite won 70.2% against a market probability of 66.2% (+4.0%, 95% [-0.3%, +8.2%], events as units); not late: 67.5% against 65.9% (+1.5%). Goes-to-decision 48.1% vs 47.8%; mean open-to-close favourite move +0.035 vs +0.038. No significant mispricing; the direction (favourites do better than priced in late matchups, so replacements may be underpriced as underdogs) is a hypothesis only. Data so far is the partial crawl (about a third of pages).

Next: re-run on the full crawl with a discovery/validation split, and only then add `late_matchup` as a feature for H4 (market-residual model). Side note for H2: in these 3,070 fights the favourite won 67.5% to 70.2% against a priced 66%, consistent with the favourite-underpriced hint, but not tested.


## Round 10 (2026-10-27): Stage 1 of the profit plan finished

**Fighter-page crawl and load.** 1,509 pages fetched (459 more skipped because their fights were already covered), 18,419 fight rows, 6,769 bouts matched into `odds_open_close` (separate file data/processed/odds_oc.duckdb). Coverage 2015 to 2025: 4,899 of 5,446 bouts (90.0%) have an opening and a closing line, 93.7% have any closing price. The two copies of each fight (one per fighter's page) agree to 0.0003 in price on average. Closing-range midpoint against the per-book median (2023-06 on, n=1,622): mean difference -0.0002, mean absolute 0.0068, 95th percentile 0.018; against the old betmma file (n=3,761): +0.0005, 0.0162, 0.055. Both meet the plan's targets (90% coverage; under 2 points). `ufcmodel/eval/betting_eval.py` (market of record, margin removal, event-clustered returns, closing-line value, loss gap) has tests.

**Replacement detection** found only 38 flagged fights with both pages read (cancelled matchups are rarely on the page): unusable.

**Late-created matchup flag** (matchup id more than 150 above its event's median; 14.8% of 6,621 fights; threshold fixed before looking), favourite result minus market probability, events as units:
- discovery 2015-2021: late +0.041 [+0.003, +0.080] (517 fights); not late -0.008 [-0.026, +0.012]
- validation 2022-2025: late +0.034 [-0.011, +0.081] (305 fights); not late +0.011 [-0.014, +0.035]
Same direction in both periods, but the validation interval includes zero, so the plan's pass rule (a validation interval excluding zero) is not met. Not adopted as a betting rule. Also noted, not tested: late fights go the distance more often (51.1% vs 48.3%). Both stay hypotheses for the market-residual model (H4), where the flag is one pre-listed feature.


## Round 11 (2026-10-27): Stage 2 of the profit plan (development period only; results in docs/stage2_results.md, script scripts/stage2.py)

**2.1 Model against the market of record, 2015 to 2025** (closing price from the per-book median where available, else the closing-range midpoint, else the old file): logistic 0.6421 vs market 0.6118, +0.0303 [+0.0224, +0.0380] over 4,923 bouts; stack +0.0330 [+0.0244, +0.0413] over 4,023. The same gap in 2015-2021 (+0.029) and 2022-2025 (+0.033). This is the honest 10-year baseline: the model is about 0.03 log loss behind the close, every period.

**H2 favourite-longshot bias** (slope of the result on logit of the market fair probability; above 1 = favourites underpriced): close, discovery 1.079 [0.966, 1.191], validation 1.156 [1.042, 1.292]; open, discovery 1.099 [0.955, 1.239], validation 1.226 [1.073, 1.383]. Same direction in all four, and the validation intervals exclude 1, but the discovery intervals include 1, so the pre-registered rule (both periods) is NOT met. Not adopted. The slope is larger at the open than at the close, as a bias the market gradually corrects would be. A slope of 1.156 means a market 70% favourite wins about 72.7% and an 80% favourite about 83.2%, a gain of 2 to 3 points against margins of 4 to 5%.

**H1 line shopping against the leave-one-out consensus** (1,145 fights with 4+ books, 2023-06 to 2025-10-24; flat 10 on the best price when price x consensus fair probability - 1 exceeds 2% or 4%): all books -10.0% [-24.3%, +3.9%] at 2% and -12.3% [-35.5%, +13.0%] at 4%; UK-reachable books -18.4% and -5.3% (101 and 45 bets, ranges wider than +-40%); exchange versions -17% to -23% (assumed price: consensus fair less a 1% spread, 2% or 5% commission). Mean closing-line value is positive (+0.05 to +0.13) only because the best of several prices always beats the consensus; the actual returns are negative. NOT kept. The likely reason, consistent with H2: the best price is usually an underdog price, and the consensus itself overprices underdogs slightly.

Net for Stage 2: no model-free edge confirmed by the pre-registered rules. One weak lead (favourites underpriced, about 2 to 3 points, bigger at the open) goes into Stage 3 as an input to H3/H4 rather than as a betting rule.


## Round 12 (2026-10-27): Stage 3 of the profit plan (H3, H4, H5; development period only; docs/stage3_results.md, docs/stage3b_results.md; scripts/stage3.py, scripts/stage3b.py)

**H3, does the model predict the opening-to-closing move: KEPT by the pre-set rule.** Coefficient on x = logit(model) - logit(open): discovery 2015-2021 +0.170 [+0.141, +0.198] (3,013 bouts), validation 2022-2025 +0.165 [+0.128, +0.203] (1,715). Robustness (scripts/stage3b.py), because the formula could be positive for a worthless model if a noisy open drifts back to the truth: with the open's coefficient freed, the model's own coefficient is +0.251 [+0.224, +0.278] and +0.291 [+0.251, +0.332] (drift back on the open is -0.08); placebos in the same formula come out NEGATIVE (constant 50% model -0.07 / -0.09, Elo probability -0.04 / -0.07, model shuffled across bouts -0.04 / -0.05). So the positive coefficient is not a drift artifact. Which features the market corrects between open and close (standardised, 2015-2025): age difference -0.098 per sd (younger fighters shorten), model gap, late matchups +0.032, reach +0.024, padding index +0.022, win streak +0.020, debut -0.019, last fight KO loss -0.013. The 'model gap' row is mechanical (the close is on both sides of that regression) and carries no meaning.

**H3 as a betting strategy** (predicted move toward a side above 0.05 logit, bet at the opening price, validation 2022-2025): 1,048 bets, return +5.0% [-2.4%, +12.8%], mean closing-line value -0.015 (the opening price carries its own margin; the move recovers most of it but not all). Not proven profitable. The pooled coefficient used for sizing the rule (0.168) was the mean of the two periods, which uses validation; it must be re-fitted on all development data when the rule is frozen.

**H4, market-residual model (11 features, offset = logit of the closing market probability): KEPT by the pre-set rule, marginally.** Ridge lambda 300 (chosen inside discovery). Validation log loss 0.5947 vs market 0.5972: -0.0026 [-0.0047, -0.0004] over 1,822 bouts (roughly p = 0.02; Holm across H3-H5 with the second-smallest p needs under 0.025, so it passes narrowly). Without the model-gap feature the gain is -0.0022 [-0.0041, -0.0003]: the gain comes from the other ten features, mainly age difference (-0.049 per sd), 'late matchup x market' (+0.053), reach difference (+0.035), debut (-0.026) and model gap (+0.052, small effect), not from the model's own probability. Deviation from the plan, flagged: feature 9 is late-matchup x logit(market) (the flag cannot say which fighter was the replacement).

**H4 as a betting strategy** (p_H4 x best sportsbook price - 1 above 3%, flat 10, 1,150 validation fights with per-book prices): best price 428 bets, return +1.1% [-11.4%, +13.3%], mean closing-line value +0.030; median price 111 bets, -11.5% [-34.8%, +15.4%]; line shopping alone at the same threshold (market probability instead of p_H4) 188 bets, -12.4% [-35.5%, +11.3%]. Not proven profitable. A log-loss gain of 0.0026 per bet is smaller than a 4 to 5% margin, so a real but small information edge needs a near-fair venue (an exchange) to pay.

**H5, residual momentum: NOT kept.** Coefficient per sd: discovery -0.071 [-0.133, -0.002], validation -0.014 [-0.100, +0.067] (sign agrees, validation interval includes zero). As a 12th feature of H4: 0.5946 vs 0.5947, no change.

**Net.** Two hypotheses pass their pre-registered rules: the model carries information the opening line lacks (H3, strong), and a market-residual model beats the closing price by a small but significant margin (H4, narrow). Neither is yet shown to earn money after margin. Candidate strategies frozen for the one-shot holdout (Stage 6): C1 = H3 open-bet rule (coefficient re-fitted on all development data, threshold 0.05 logit, price = the opening line); C2 = H4 with the discovery coefficients saved in data/processed/stage3.pkl, bet when p_H4 x best price - 1 exceeds 3%. Neither is a recommendation to stake money. Forward capture of opening-week prices at UK-reachable books is now the deciding evidence.


## Round 13 (2026-10-27): the frozen Stage 3 candidates on past events, GBP 50 per event (scripts/past_test.py, scripts/past_test2.py; development period only)

**C2 (H4 market-residual model), per-book prices, 2023-06 to 2025-10-24, 102 events.** Quarter Kelly x 50, 3% edge, max 10 a fight. Best price: 433 bets, staked 289, profit +15.09, ROI +5.2% [-8%, +21%], 51/102 events in profit, mean closing-line value +0.030; by year +13, -14, +16. Median price: 111 bets, staked 52, ROI -6.8% [-32%, +19%]. Line shopping alone: 191 bets, ROI -0.1%. Tiny stakes (about 3 a event) and every interval includes zero: nothing shown.

**C1 (H3 opening-line rule), opening prices, 2022-01-01 to 2025-10-24, beta fixed from discovery (0.1698), 162 events.** 1,054 bets, staked 7,760, profit +581.43, ROI +7.5% [-1%, +16%], 87/162 events in profit, positive every year (2022 +152 on 1,950, 2023 +205 on 1,990, 2024 +98 on 2,090, 2025 +127 on 1,730). Mean closing-line value -0.015 (the opening price carries its own margin, but the outcomes beat the closing fair probability).

**Is it the model or just the favourite bias at the open?** All favourites at the open: -2.4% (1,715 bets). C1 bets on open favourites only: +14.8% [+7%, +22%] (265 bets); on open underdogs only: +2.4% [-7%, +12%] (789 bets, mean price 3.09). The model's pick at the open in every fight, no threshold: +7.3% [+3%, +11%] (1,715 bets). Random sides of the same fights, 200 shuffles: mean -5.8%, 5th to 95th percentile [-11.1%, 0.0%]; C1 beat 100% of them. So the result is the model's information, not a favourite tilt and not chance.

**The decisive caveat.** The same model's picks lose at closing prices (-5.4% at the median close, 2023-06 to 2025-10). All the apparent profit sits in the opening line. Whether a UK bettor can actually bet that opening price is unknown: the site's 'Open' is one book's first line, maybe with tiny limits, maybe gone within minutes, maybe not offered to UK accounts. The forward capture (slots listed, Monday, Thursday, pre-event) is the test of what price is really available and when. Until then C1 is a hypothesis about a price that may not be tradable, not a strategy to stake money on. (Possible realism check on existing data, not yet done: each fighter page carries a 10-point price-history sparkline per fight; the rule could be re-priced at the mid-history point as a stand-in for a Monday price.)


## Round 14 (2026-10-27): the opening-line rule re-priced along each fight's price history (scripts/midweek_test.py)

Each fighter page carries a 10-point price series per fight (index 0 = the open, index 9 = the close; spacing in time not documented). 11,252 series were matched to bouts; index 0 equals the page's opening price exactly. The other side is rebuilt by holding the opening margin fixed (rebuilt open vs actual open: mean absolute price difference 0.0013). The C1 rule is applied at each index as a bettor would see it at that moment (selection and price both from that index), flat 10 per bet, 1,703 fights in 2022 to 2025-10-24:

| Index | Bets | ROI [95%, events as units] |
|---|---|---|
| 0 (open) | 1,045 | +5.1% [-2.4%, +12.9%] |
| 1 | 1,042 | +0.1% [-7.6%, +7.6%] |
| 2 | 1,032 | +1.0% [-6.6%, +8.6%] |
| 3 | 1,044 | +0.1% [-7.7%, +7.9%] |
| 4 | 1,044 | -1.3% [-9.1%, +6.5%] |
| 5 | 1,042 | -1.4% [-9.3%, +6.7%] |
| 6 | 1,049 | -2.1% [-10.2%, +6.2%] |
| 7 | 1,048 | -1.5% [-9.9%, +6.7%] |
| 8 | 1,056 | -3.3% [-11.5%, +5.0%] |
| 9 (close) | 1,075 | -2.8% [-11.1%, +5.4%] |

The profit exists only at the first price. By the second point it is gone (+0.1%), and around the middle of the history it is -1.3%, about where the model's picks sit at closing prices. If the points are spread evenly in time, a Monday price offers no edge. If the first step covers only hours, the edge lives in the first hours after the line opens, which a bettor cannot realistically reach and which our forward capture (front page checked every 6 hours, slot 'listed') would miss too. The rebuild of the other side's price holds the opening margin fixed, so it is approximate away from index 0.

Conclusion for C1: the opening-line result is real in the data but not shown to be tradable. It is a statement about the first line the site recorded. It should not be used to stake money. The forward test still runs (it measures what price is actually available at each point), but expectations are low.


## Round 15 (2026-10-27): confident picks, whatever the value (exploratory, read-only; scripts/negative_value_test.py, confidence_cut_test.py, confidence_cut_early.py)

Asked: what if we bet the model's pick even when its value is negative, and what if the cutoff is 80% confidence. GBP 50 per event split equally (max 10 a bet), stack model out-of-sample.

**Negative-value picks (2023-06 to 2025-10, 102 events, real sportsbook prices).** 676 picks, hit 71.4%, return -5.2% at the median price [-10%, -1%] and -2.3% at the best price [-7%, +2%]; positive-value picks +1.4% and +4.0%, intervals include zero. A high win rate is not profit when the price is short.

**Confidence cutoffs, all picks at or above the cutoff (2023-06 to 2025-10):** 70%: 254 bets, hit 81.1% (model says 76.3%, market says 73.3%), +6.6% at the median price [0%, +13%], +8.6% at the best price [+2%, +15%]; 75%: 137 bets, +2.1% / +4.1%; 80%: 52 bets over 40 events, hit 86.5% (model 83.5%, market 76.9%), +8.4% [-4%, +20%] / +10.2% [-3%, +23%]; 85%: 15 bets, +9.5% / +11.3%; 90%: no picks.

**Replication on earlier years not used for the first look (2017-01 to 2023-05, 262 events, prices from the closing range: mid = typical, high = best):** 70%: 588 bets, hit 74.8% (model 76.0%, market 69.6%), +3.7% [-2%, +9%] mid, +5.5% [0%, +11%] high; 75%: 306 bets, +5.0% / +6.7%; 80%: 108 bets over 83 events, hit 85.2% (model 83.3%, market 77.3%), +5.5% [-3%, +13%] / +7.1% [-2%, +15%]; 85%: 21 bets, +1.4% / +2.8%. All picks at 50%: +0.3% mid, +2.6% high.

**Reading.** In both periods the model's most confident picks win about as often as the model says and 6 to 8 points more often than the market says, which is the favourite underpricing H2 pointed to. The returns are positive in both periods (about +4% to +8%), but each individual interval includes zero or just touches it, 80% rests on 160 bets in total, and the cutoff ladder was scanned (70 to 90), so this is exploratory, not a pre-registered pass. Losses cost 3 to 4 stakes of winnings each (mean price 1.27 to 1.46), so a small shift in hit rate moves the return a lot. Not adopted as a rule. The natural next step is a pre-set forward paper rule (model pick of 70% or 80% and above, best sportsbook price) so it can be checked on cards not yet fought.


## Forward paper rule C3_v1 registered (2026-10-27, before any card was fought)

Rule: at every capture slot (listed, mon, thu, pre; plus any manual run), for each fight with a model prediction, log the model's pick when the no-market stack probability is at least 70% (tier '70-80'), flagged '80+' from 80%, with the best sportsbook price and book, the median price and the de-vigged market probability for the same side. File: data/paper/confident_picks.csv (code: confident_row in src/ufcmodel/reports/livecard.py, tested in tests/test_confident_rule.py). Exchange prices (Polymarket, Kalshi) are excluded from the best price. It sits beside the earlier paper-bet rule in paper_log.csv and changes nothing in it.

Grading plan, fixed now. After each card, join the picks to the results (needs the results data updated) and report, per slot, per tier and for the first scheduled slot that has a price: hit rate against the model's and the market's probability, and the flat-10 return at the best price and at the median price, with intervals from a bootstrap over events. Judged after at least 150 picks at 70+ (about 40 at 80+): keep only if the return interval is above zero, otherwise drop. No real money before then. The earlier evidence (decisions.md Round 15) was exploratory: +3.7% to +8.6% at 70+ and +5.5% to +10.2% at 80+ across two periods, each interval touching zero.

First logged (manual snapshot, Vegas 123, 2026-10-27 21:34 UTC): Luana Santos over Yana Santos, model 84.0% [80+], market 71.2%, best price 1.37 (Caesars), median 1.36.


## Round 16 (2026-10-27): parlays with hedges as risk management (read-only; scripts/parlay_hedge_test.py, parlay_hedge_early.py)

GBP 50 per event, legs = the 3 or 4 most confident model picks on the card (average model confidence 72%), a parlay paying the product of its legs' single prices (an assumption that flatters parlays: books often shave them further, and a cancelled fight voids a leg).

| Structure | 2023-06 to 2025-10 (102 events, real book prices) ROI [95%], sd per event, events in profit | 2017 to 2023-05 (262 events, closing-range prices) |
|---|---|---|
| singles on the top 4 | +6.4% [0%, +13%], sd 15.9, 58/102 | +2.0% [-3%, +6%], sd 18.3, 144/262 |
| 3-leg parlay | +16.2% [-13%, +48%], sd 77, 47/102 | +6.1% [-13%, +25%], sd 80, 94/262 |
| 4-leg parlay | +31.6% [-8%, +77%], sd 106, 37/102 | +4.4% [-21%, +34%], sd 114, 59/262 |
| 4-leg parlay + singles on the same legs | +19.0% [-3%, +44%], sd 60, 37/102 | +3.2% [-12%, +20%], sd 64, 59/262 |
| 4-leg parlay + insurance (bets on the other side of the same 4 fights) | +13.1% [-11%, +41%], sd 68, 37/102 | -2.0% [-19%, +17%], sd 75, 60/262 |
| Yankee (6 doubles, 4 trebles, 1 fourfold) | +17.5% [-2%, +38%], sd 52, 41/102 | +3.9% [-9%, +18%], sd 55, 82/262 |

Reading. Every structure is a weighted sum of bets whose own expected return is the same small number, so a structure cannot add edge; it changes how that edge (and the bookmaker's margin) is multiplied and how widely results swing. Parlays multiply a small per-leg edge (the favourite underpricing of H2) across legs, which is why the 4-leg parlay looks best in the recent period, but the same structure returned only +4.4% in the earlier 262 events, and every interval includes zero. In the recent period the 4-leg parlay lost the whole 50 in 65 of 102 events. Hedges do not protect the downside (the worst event stays -42 to -50) and the insurance variant gives up return (opposite-side bets pay the margin twice). On a return-per-risk basis singles are the best (return per event divided by sd: 0.20 and 0.05 against 0.15 and 0.04 for the 4-leg parlay and 0.17 and 0.04 for the yankee). The yankee is the only structure that makes a parlay-style payoff less all-or-nothing (more events in profit than the straight parlays). Not adopted; nothing here was added to any rule.


## Round 17 (2026-10-27): stake more of the 50 per card (scripts/stake_more_test.py; ufc-ui staking rule changed)

Asked to use more of the 50 per card. Same value bets and probabilities, 102 cards with real prices (2023-06 to 2025-10-18), best sportsbook price: quarter Kelly (the old setting) staked 2.99 a card, +5.7 profit, +1.9% [-10%, +15%]; half Kelly 5.94 a card, +16.8, +2.8%; full Kelly 11.68 a card, +44.4, +3.7% [-10%, +17%], worst card -15.5, 48 of 102 cards up; deploying the whole 50 on the same bets 46.77 a card, +21.2, +0.4% [-12%, +14%], worst card -50.0, standard deviation 32 a card; deploying the whole 50 on every positive-edge side -81.4, -1.6%. More stake scales profit and risk together and creates no edge: every interval still includes zero. Change made: Kelly fraction 0.25 to 1.0 in scripts/signal_data.py (the UI's stakes), still halved for thin data and a gap above 15 points, 3% minimum edge, 20% cap per fight. Not used: deploying the full budget (it risks the whole 50 on a card without earning more). Vegas 123 now stakes 5.77 over 4 bets (was 1.43). Full Kelly assumes the edge estimate is right; if the model's edge is smaller than estimated, this overbets, so treat it as the upper end and keep it paper-only until the forward test passes.


## Round 18 (2026-11-03): first graded card, UFC Vegas 123 (scripts/grade_results.py, data/paper/results.json)

Results refreshed with `ufcmodel update` (+12 bouts, latest event 2026-10-31 in the results source, listed as Nov 1 on the odds site). Predictions are the last capture before the card (the Thursday slot; the pre-fight slot was missed because the computer had no network that evening). 11 of 12 predicted fights scored; Kropschot vs Klein has no result in the data (cancelled or not yet in the source), and Petroski vs Bekoev had no sportsbook price so was never predicted for scoring.

Winners picked: model alone 7/11 (64%, 95% range 35% to 85%), blend 8/11 (73%, 43% to 90%), market 8/11, Elo 6/11 (55%). Log loss on the 11 priced fights: model 0.607, blend 0.528, market 0.519, Elo 0.684, coin flip 0.693 (Brier 0.211, 0.174, 0.171, 0.245). Where model and market disagreed (3 fights): model right 1 (Nolan), market right 2. Calibration of the model's picks: 50-60% said 57%, right 5/8; 60-70% said 63%, right 1/2; 70%+ said 84%, right 1/1.

Staking-rule bets (as exported on 2026-10-27, full Kelly, 50 budget): 1 of 4 won (Nolan at 2.14, stake 2.82, +3.21); Gall, Berggren and Lisboa lost (-1.58, -0.91, -0.46): staked 5.77, profit +0.26; at the 1,000 budget scale +5.30 on 115.40 staked. Paper-test pick Luana Santos (80%+) won: +3.64 on 10 paper. Forward test: 1 of 150 needed picks graded. The Opus judge's single recommended bet (Nolan, 1.00) would have returned +1.14; the rest of its passes avoided the three losses.

Reading: 11 fights cannot separate skill from luck (a coin flip picks 7 or more of 11 right 27% of the time). The market was ahead on probability quality again, consistent with every past test. Nothing here changes the plan: keep paper-only until the forward test has 150 graded picks.
