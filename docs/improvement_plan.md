# Improvement plan (written 2026-10-27)

Status (2026-10-27): 1a done (1,704 bouts with real prices), 1c done on the development period (market beats the model,
no profitable rule), 2a done (no variant helped; see `docs/drift_test.md` and the decision log). Superseded for betting work by
`docs/profit_plan.md` (written 2026-10-27), which folds in 1b, 2b, 2c, 3a and 5.

Goal: find out whether the model can beat realistic prices, and improve it where the evidence says it is weak.
Everything stays free. No real money until the paper-trading gate passes.

## Ground rules for every step

- Tested walk-forward on the development years only (2015 to 2025-10-24). The holdout is not re-scored.
- Success is decided before the run: a change is kept only if log loss improves with a paired-bootstrap 95% interval below zero
  (or, for method/round changes, the simulator's own metrics improve the same way). Otherwise it is dropped and logged.
- Each step gets an entry in `docs/decisions.md`, kept or not.
- One change at a time, so each result is attributable.

## Phase 1: realistic odds (most important; everything else is judged against these)

**1a. Backfill real historical odds for 2023-09 onward (me).**
Best Fight Odds keeps an archive page per event with opening and closing lines. If its robots.txt and terms allow reading,
fetch the ~120 events since the old odds file ends, slowly (one page at a time, with pauses), and store them in
`odds_snapshots` with `kind = 'open' | 'close'` and the bookmaker spread. If the site blocks or disallows it, stop and say so.
- Done when: recent events have closing odds, and QA reports their overround (should be about 1.04 to 1.08).
- Payoff: the betting tests and the model-vs-market comparison can be run on real prices instead of the stand-in file,
  and closing-line value (CLV) can be measured for the first time.

**1b. Weekly odds capture for upcoming cards (me, with you checking).**
For each card, read the odds page several times through fight week (for example on announcement, mid-week, and the day of the
fights) and append timestamped rows. You check the prices against what your bookmaker offers and note any big difference.
- Done when: `ufcmodel fightweek` reads the latest snapshot automatically and the paper log records the price at bet time.

**1c. Re-run the betting tests on real prices (me).**
Repeat `scripts/flat10.py`, `scripts/value10.py` and the Kelly simulation on the backfilled odds.
- Done when: a short report says whether any rule beats real prices, with 95% intervals.

## Phase 2: fix known weaknesses (me; can run while Phase 1 data comes in)

**2a. Finish-rate drift.**
Problem: in the last 20 events 33% of fights went the distance against 45% expected.
Change: give the simulator's finish calibration a recency weight (for example a 12 to 24 month half-life) instead of the
fixed 150-bout window, and test a division-level finish trend feature in the direct method model.
- Files: `eval/phase8.py` (`sim_walk_forward`, `finish_ratios`), `sim/simulator.py`.
- Kept if: goes-the-distance log loss and round-of-finish log loss improve on the dev folds, and the expected share of
  decisions in recent dev years moves toward the actual share.

**2b. Short-notice and late-replacement fights.**
Change: flag a fighter who took the bout within about 3 weeks of the event. Needs a source of announcement dates; if none is
freely available, use a proxy (opponent change visible on the event page) or drop the idea.
- Kept if: the flag improves winner log loss with the usual test.

**2c. Thin-record fighters.**
Change: add pre-UFC record features (fights, win rate, finish rate, level of promotion) for fighters with fewer than 3 UFC bouts.
Source must be free and permit reading; check terms first. If no source works, instead widen the shrinkage toward the
division average for debutants and test that alone.
- Kept if: log loss improves on bouts involving a debutant, without hurting the rest.

## Phase 3: find where the model adds value over the market (me, after Phase 1)

**3a. Disagreement analysis on real prices.**
Split bouts by type (heavy underdog, debutant, short notice, title fight, division, big model-vs-market gap) and check
model-vs-market log loss and CLV in each. Keep the number of splits small and fixed in advance to avoid finding noise.
- Done when: a table shows which, if any, groups beat the market with intervals that exclude zero.

**3b. Narrow betting rule.**
Only if 3a finds a group: build a rule that bets only that group and paper-trade it forward. No back-test tuning beyond
what 3a fixed in advance.

## Phase 4: information only you can add (you, at your own pace)

**4a. Context facts** (injury news, missed weight, camp change, layoff reason) for each upcoming card, entered in the
`context` table before the fights. I'll make a simple form or CSV template for this.
**4b. Style tags** with `tools/tagger.html`, starting with fighters on upcoming cards.
These only help once there are a few hundred bouts entered, so the model ignores them until then.

## Phase 5: forward test (both, ongoing)

Every card: log predictions and odds before the fights, grade after, and update a running record of log loss vs market,
CLV and paper profit at £10 flat. The paper-trading gate (a few hundred bets, positive CLV with an interval above zero)
decides whether real betting is ever worth considering.

## Not planned

- Bigger or more complex models: the data is thin and they mostly add overfitting.
- Re-scoring the holdout.
- Paid data or tools.

## Order and rough effort

| Step | Who | Effort | Depends on |
|---|---|---|---|
| 1a backfill odds | me | 1 session | site allows reading |
| 2a finish drift | me | 1 session | none |
| 1b weekly capture | me + you check | ongoing, small | none |
| 1c betting on real prices | me | short | 1a |
| 2b short notice | me | 1 session | a free date source |
| 2c thin records | me | 1 to 2 sessions | a free source |
| 3a/3b disagreement analysis | me | 1 session | 1a |
| 4a/4b context and tags | you | ongoing | none |
| 5 forward test | both | every card | 1b |
