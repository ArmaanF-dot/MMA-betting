# Profitability plan (written 2026-10-27, before any of these tests were run)

Status: Stage 1 is done (coverage 90.0%, agreement under 1 point; see decisions.md Round 10). Stage 2 and Stage 3 are done (see decisions.md Rounds 11 and 12): H3 and H4 passed their rules, H1, H2, H5 did not. Stage 4 onward not started.

This file is also the pre-registration: the hypotheses, data splits, thresholds and kill rules below are fixed now, before
looking at the data they will be tested on. Changes later must be logged in `docs/decisions.md` with the reason.

## Where we stand

- On real closing prices (1,150 fights, 2023-06 to 2025-10) the market's log loss is 0.589 and the model's 0.624: the model is
  0.035 worse, and a 50/50 blend is still slightly worse than the market alone.
- Every £10 rule tested on real prices loses or breaks even. Betting the model's pick returns -5.4% at the median price but +0.4%
  at the best price across six books: shopping for the best price is worth about 5 to 6 points of return by itself.
- Market favourites lose only -1.3% at the median price although the books' margin is 4 to 5.5%. That hints that favourites are
  slightly underpriced (a favourite-longshot bias), but it is not established.
- Props: the market beats the model on goes-the-distance (+0.014 for the best model) and on wins-inside-distance (+0.019).
  Decisions were underpriced in 2023 to 2024 and the gap closed in 2025, so that looks like a drifting regime, not an edge.
- Checked today: Best Fight Odds fighter pages list every fight with its opening line, closing range (lowest to highest price
  across books at the close) and movement. Old event pages only show today's books, so before 2023-06 the history has to come
  from the fighter pages (a 2015 page parsed 13 fights with no prices).

## What "profitable" has to mean

1. **Beat the closing price first.** Closing-line value (CLV: the price you took against the fair closing price) is the standard
   test of a real edge, and it needs far fewer bets than profit does. A 2% average CLV can be confirmed in roughly 50 to 100 bets.
   Confirming a 2% return on stake needs thousands, because single bets swing so much.
2. **Use prices you can actually get.** The odds site mostly lists US books. You are in the UK, so the realistic venues are UK
   books (which restrict accounts that win) and betting exchanges (low margin, 2 to 5% commission on winnings).
3. **Expect small numbers.** Even a real edge in MMA is likely 1 to 3% per bet. At £10 flat on about 150 bets a year that is
   roughly £15 to £45 a year expected, with swings of ±£150. The main prize is a clear answer to whether an edge exists.

## Where an edge could come from, most promising first

1. **Timing.** Opening lines are set by one or two books with little money behind them. The close is far sharper. If the
   model's disagreement with the opening line predicts which way the line moves, betting early captures value. This is the
   main hypothesis, and the fighter pages make it testable for about 10 years of fights.
2. **Price.** Line shopping and exchanges cut the margin from about 5% to 1 to 2%. That alone turns a near-zero edge into a
   possible small profit, and it is model-free.
3. **Known betting biases.** Favourite-longshot bias, and the public overrating things that look good on paper: stats padded
   against weak opposition (your Murzakanov point), long win streaks, big names. Also underrating age decline and fighters coming
   off knockout losses. Each is one testable feature.
4. **Props priced from generic finish rates.** Over/under rounds and method markets carry big margins, but books price them more
   crudely than winners. A fighter-specific finish-time model might find mispricing there.
5. **Accuracy of the model itself.** This is useful mainly as an input to 1 to 4. More stats on winners have stopped helping;
   the big gains left are market-based ratings, debutant priors and short-notice flags.

**Not worth doing:** bigger models, more winner stats, parlays for their own sake (a parlay only makes sense when every leg
already has a proven edge), or real money before the gate in Stage 6.

## Ground rules (pre-registered)

- **Data splits:**
  - Discovery: 2015-01-01 to 2021-12-31, for finding effects.
  - Validation: 2022-01-01 to 2025-10-24, for confirming them. Per-book prices exist from 2023-06.
  - Betting holdout: 2025-10-25 to 2026-10-24, scored once with frozen strategies. No market comparison has been run on it yet.
    The model-only holdout report was scored once earlier and is a separate thing.
  - Forward: from Vegas 123 (2026-11-01) onward, paper only.
  - Known contamination: the 2026 decision rate (33%) is already known, so goes-the-distance rules get no credit from the holdout.
- **Market of record:** the consensus fair probability, with the margin removed from each price pair.
  - From 2023-06: the median across sportsbooks.
  - Before 2023-06: the midpoint of the closing range on the fighter pages.
  - The old betmma file is used only as a cross-check.
- **Metrics:**
  - Log loss against the market, with a paired bootstrap.
  - CLV per bet: ln(price taken × fair closing probability of that side).
  - Return at £10 flat, with intervals from a bootstrap clustered by event, since fights on one card are not independent.
- **Pass rule:** an effect must be found on discovery, then confirmed on validation with a 95% interval excluding zero, using a
  Holm correction across hypotheses H2 to H5. Only survivors reach the holdout.
- **Kill rule:** if nothing survives validation, stop the betting research. The conclusion is that public free data gives no edge.
- **Thresholds:** fixed below. No tuning on validation or the holdout.
- **Free and polite:** public pages only, one request at a time with a 4 s pause, resume from cache, and stop on any block or bot
  check. Raw pages stay local and are never redistributed.
- **Asks before acting:** anything persistent (a scheduled capture), anything needing an account or key, and anything with real
  money is your call, asked first.

## Stage 1: data (me; about 1 session plus a few hours of background crawling)

**1.1 Fighter-page crawl.** Fetch the pages of every fighter with a UFC bout since 2014, about 2,000 to 2,500 pages.
- Parse every fight row: event, date, opponent, opening price, closing range low and high, movement.
- Store in a new table `odds_open_close`, matched to bouts by fighter pair and date as in `ingest/bfo.py`.
- Keep fights in other promotions too (needed for debutant priors, 5.2).
- Done when: at least 90% of UFC bouts since 2015 have an open and a close.
- QA:
  - Against the per-book data (2023-06 on): mean absolute difference under 2 points of win probability.
  - Against the betmma file: same check, no bias.

**1.2 Market of record.** Build one function returning open and close fair probabilities, best prices, number of books and
spread for any bout. Every later test uses it.

**1.3 Line timestamps (probe only).** The price cells open a line-movement chart.
- Find its data request, check robots.txt and size, and fetch a sample of 20 fights.
- If it gives timestamped history for one request per fight or less, fetch it for 2023-06 onward. That gives true opening times,
  plus prices at the moments a UK bettor could act.
- If it needs one request per book per side, skip it.

**1.4 Short-notice flag.** A fight added late carries a matchup id far above the other fights on its event.
- Flag fights whose id is above the event's 90th percentile by a gap measured on known late replacements.
- Or use the opening timestamp from 1.3 if it exists.
- Check the flag by hand on 20 fights.

**1.5 One shared betting-evaluation module** (`ufcmodel/eval/betting_eval.py`).
- Replaces the ad-hoc scripts (`flat10`, `value10`, `real_odds_test`, `prop_test`).
- Provides: de-vig, market of record, flat-stake return with event-clustered intervals, CLV, and log loss against the market.
- Comes with tests.

## Stage 2: model-free edges (me; 1 session)

**2.1 Re-score the model against the market of record, 2015 to 2025.** This replaces the stand-in odds in all earlier
comparisons, and the 10-year gap becomes the honest baseline. Nothing is chosen here.

**H1, consensus outliers and line shopping** (per-book data, validation period).
- Bet when one book's price × the leave-one-out consensus fair probability − 1 exceeds 2% or 4%.
- Report return, CLV against the close, and whether the consensus is itself calibrated.
- Also report the "UK-reachable books only" subset (BetWay, Unibet) and an exchange version.
  - Exchange price assumed: the fair price minus a 1% spread, then 2% or 5% commission on winnings. This is an assumption.
- Keep if: the return interval is above zero on validation for at least one fixed threshold.

**H2, favourite-longshot bias** (discovery, then validation).
- Logistic regression of the result on logit(market fair probability), at the open and at the close.
- A slope above 1 means favourites are underpriced; below 1 means overpriced.
- Keep if: the slope differs from 1 with the interval excluding 1 in both periods, in the same direction.
- Strategy if kept: adjusted probability = sigmoid(slope × logit(market)). Bet when adjusted probability × best price − 1
  exceeds 2% or 4%.

## Stage 3: does the model know anything the market only learns later? (me; 1 to 2 sessions)

**H3, opening-line movement** (main hypothesis).
- Regress Δ = logit(close) − logit(open) on x = logit(model) − logit(open), with event-clustered standard errors.
- Also add the H4 features below as predictors of movement, to see which biases the market corrects by the close.
- Keep if: the coefficient on x is above zero with the interval excluding zero, on discovery and again on validation.
- Strategy if kept: bet at the open when the predicted move toward that side exceeds 0.05 logit.
  - Measure CLV, and the return at the open price.
  - The open is a specific book with low limits, so also measure, from forward captures, whether the edge is still there at UK
    books on the Monday of fight week.

**H4, market-residual model.**
- A logistic model with logit(closing market fair probability) as a fixed offset, plus these 11 features, fixed now. All are
  differences between the two fighters, and the model is fitted in both corner orders.
  1. age difference
  2. aged 35 or over
  3. layoff of a year or more
  4. last fight lost by KO/TKO
  5. KO/TKO losses in the last 3 fights
  6. padding index: raw strike differential per minute minus the opponent-adjusted differential
  7. win streak of 3 or more
  8. UFC debut
  9. short notice (from 1.4)
  10. reach difference
  11. the model gap, logit(model) − logit(market)
- Ridge penalty chosen by a time split inside discovery. Fit on discovery, scored on validation.
- Keep if: validation log loss beats the market, with the paired interval below zero.
- Then bet when the H4 probability × best price − 1 exceeds 3%. Report CLV and return.

**H5, residual momentum.**
- Does a fighter's past "beat the odds" record predict future results against the odds?
- Measure: the fighter's past sum of (result − market probability), shrunk by fight count.
- Tested as a twelfth feature and on its own coefficient. Keep if the interval excludes zero on discovery and validation.

**3.4 Survivors become candidate strategies** with fixed rules, ready for the holdout. If H3, H4 and H5 all fail, the model has
no betting use beyond what the market already shows, and the fight-week report says so plainly.

## Stage 4: props (me; 1 to 2 sessions; validation period only, since prop history starts 2023-06)

**4.1 Finish-time model.**
- A discrete-time hazard of a finish in each 30 seconds of the fight. Features:
  - each fighter's KO and submission rates, for and against
  - durability
  - division
  - scheduled rounds
  - how lopsided the moneyline is (market information is allowed here)
- Trained on fights before 2022.
- This prices over/under 1.5 and 2.5 rounds (3.5 and 4.5 in five-round fights), which the current round-level simulator cannot.
- Compare against the consensus over/under prices with the margin removed. Bet when model × best price − 1 exceeds 5%.
- Keep if: log loss beats the market, interval below zero.

**4.2 Method market as a 6-way market.**
- Per book, combine the six method props (each fighter by KO, submission or decision) into one market with the margin removed.
  Take the median across books.
- Compare with the direct 6-class model.
- These props carry 15 to 25% margins, so the betting rule only fires when model × best price − 1 exceeds 10%.

**4.3 Goes-the-distance: forward watch only.** Log the decision prices every card. No betting rule unless one is defined in
advance from 2023 to 2025 and then passes forward.

## Stage 5: accuracy upgrades that feed Stages 3 and 4 (me; 1 session)

**5.1 Market rating.** An Elo-style rating that learns from past closing odds instead of results, with decay over time.
- Expected to close much of the model-to-market gap.
- Kept as a separate "market-aware" model, so the market-free model still exists for H3 and H4.
- Keep if: development log loss improves, interval below zero.

**5.2 Debutant priors.** Use the closing odds from a debutant's pre-UFC fights on the fighter pages (Contender Series, regional
promotions) as their starting rating. Test on debut fights only.

**5.3 Short-notice feature** (from 1.4) in the main model. Usual test.

**5.4 Market-aware fight-week report.** Show the market's fair probability first, then the market-aware model, the edge, and
whether any surviving strategy fires. Default to "no bet" unless one does.

## Stage 6: one-shot holdout, then forward paper trading (both)

**6.1 Freeze and score the betting holdout once.** Run every surviving strategy on 2025-10-25 to 2026-10-24 and report the
result as it is in `docs/decisions.md`. Nothing is changed afterward, whatever the result.

**6.2 Forward capture for each card.**
- Prices at four points:
  - when the fight is first listed
  - Monday of fight week
  - Thursday
  - about 2 hours before the event, as the closing proxy
- Doing this automatically needs a Windows scheduled task, which is persistent configuration, so I'll ask first. Otherwise you
  run `python -m ufcmodel.reports.livecard <event url> <date>` at those times.
- After each card I grade every strategy (CLV and return) and update a running summary. A private tracker page is optional.

**6.3 Gate before any real money.** All three must hold:
- at least 200 forward paper bets across at least 15 cards
- average CLV above zero with the 95% interval above zero
- the return interval not entirely below zero, and the holdout not contradicting it

Even then it is your decision, at small fixed stakes with a hard loss limit you can afford.

## What I need from you

- Nothing to start Stages 1 to 5: they use free public pages and data already here.
- Later:
  - Yes or no on the scheduled capture in 6.2.
  - For paper bets, the price you could actually get at a UK book or exchange at the time, since the odds site does not list
    UK books.
  - Optional: a free odds-API key, if you want UK prices captured automatically. You add it to an environment variable
    yourself; I will not handle it in chat.

## Most likely outcome

- The market-free model stays behind the close.
- The best chances are a timing edge against opening lines (H3), the price advantage of shopping and exchanges (H1), and maybe
  a favourite-longshot tilt (H2).
- If all of those fail on validation, the honest result is that public free data gives no betting edge in UFC. That is still a
  useful answer.

## Order and effort

| Step | Who | Effort | Depends on |
|---|---|---|---|
| 1.1 to 1.5 data, short-notice flag, shared evaluation module | me | 1 session + 2 to 4 h background crawl | nothing |
| 2.1, H1, H2 model-free tests | me | 1 session | 1.1, 1.2, 1.5 |
| H3, H4, H5 opening-line and residual tests | me | 1 to 2 sessions | 1.1 to 1.5, 2.1 |
| 4.1 to 4.3 props | me | 1 to 2 sessions | 1.5 |
| 5.1 to 5.4 accuracy upgrades and report | me | 1 session | 1.1, 1.4 |
| 6.1 holdout, scored once | me | short | Stages 2 to 5 frozen |
| 6.2 and 6.3 forward capture and gate | both | every card | 6.1; your yes for automation |

Compute limits: about 1.8 GB of free memory and a single database writer. Crawls run alone, and analysis runs no more than three
jobs at a time.

