# Verdict: UFC Vegas 123

Checked against ufc-ui/data.json and docs/decisions.md. Every stake below is paper money. decisions.md says to keep the staking rule paper-only until the forward test passes, and the forward log has 1 pick logged and 0 graded.

## 1. The five points

**Tom Nolan 2.14: REDUCE to 1.00, and only at 2.10 or better.** No flags, 20 and 6 prior fights, and the model's own pick (59.7%) agrees. It is the only bet that still has value on the market's number, but only just: +1.0% at 2.14 and -5.6% at the median price of 2.00. The 2.14 comes from BetRivers, a US book, so a UK account probably cannot get it.

**Mickey Gall 3.65: PASS (0).** If the market is right, the bet loses 4.2% at 3.65 and 10.8% at the median. It carries two flags: a 715-day layoff and an unknown opponent age. The blend did not "price the layoff", as FOR claims. It is a fixed mix of about 80% market and 20% model in every fight, and the model's layoff penalty is already inside its 45.5%.

**Theodor Berggren 2.50: PASS (0).** Each fighter has one fight in the data. Halving the stake for thin data only admits that the probability is weak. If the market is right, the bet loses 3.9%.

**Tainara Lisboa 5.60: PASS (0).** Szabova is not in the data. The whole edge comes from a model that is 26 points away from the market, and if the market is right the bet loses 13.5%.

**Luana Santos (paper pick): BET as registered, 10 on paper and 0 real.** The C3_v1 rule was fixed before any card was fought, so logging this pick is the test itself. Skipping it would spoil the record. On its own merits it would fail: the blend edge is +1.7%, under the 3% minimum, and the 80%+ cutoff was picked after scanning cutoffs from 70% to 90%.

## Where the advocates got facts wrong

- AGAINST: "model alone has Nolan at 40.4%" is wrong. That 40.4% is Moicano's figure, so the model gives Nolan 59.7%.
- AGAINST: -10.0% is the line-shopping result across all books, not UK books. The UK-only figure, -18.4%, rests on 101 bets with a range wider than ±40%. That test also covered all line-shopped bets, not just underdog prices.
- AGAINST: when the best price (5.60) equals the median, at least half the books offer it. It does not mean one book is the only source.
- AGAINST: the mid-week fade (+5.1% falling to -1.3%) belongs to the opening-line rule C1, not to this staking rule. The -11.3% result for edges above 5% was measured at typical prices, not best prices. It is still the only interval that excludes zero, and it counts against large edges.
- FOR: the +5.2% on 433 bets comes from the old quarter-Kelly test. The full-Kelly rule in use now returned +3.7% (range -10% to +17%), and the same test lost 6.8% at the median price. "Favourites underpriced, slope 1.156" did not meet its own pre-set rule, because the discovery-period interval includes 1.

## 2. Overall call for the card

**Overall: stake 1.00 of 50 on paper, on Nolan only, and only at 2.10 or better at a UK book. Otherwise pass the card. Log Santos on paper as registered.**

What I expect to earn: about zero, somewhere between -0.06 and +0.06 on that 1.00. On the full 5.77, my honest range is about -0.60 to +0.20. That is worse than the model's claimed +0.38, because the model trails the market by 0.030 log loss (range 0.022 to 0.038) in every period. Full Kelly also assumes the edge estimate is correct, so on untested edges it overbets.

## 3. What would change my mind

- About 40 graded 80%+ picks under C3_v1 with a return interval above zero.
- Forward logs showing that a UK book offers prices like these on Monday or Thursday.
- A forward run of the staking rule on 50 or more cards that beats closing prices.
- A backtest of 5%+ edges at best prices that no longer loses.

## 4. Limits of this debate

Both advocates are language models reading the same files. They add no new data, so agreement between them is not independent confirmation. Each picked the numbers that suited its side. One card of four bets is pure noise and cannot settle anything. The only thing that adds evidence is the graded forward log.
