# Case against placing bets: UFC Vegas 123

Shared facts. Total proposed stake is 5.77 of 50. All four edges are above 5%, and the backtest bucket "value bets, edge above 5%" lost 11.3% at typical prices (835 bets, range -20.9% to -2.1%), the only interval that excludes zero. The model trails the market by 0.030 log loss (range 0.022 to 0.038). Every best price below is at a US book (Caesars, BetRivers); I cannot verify a UK account can get any of them.

## Tom Nolan at 2.14 (BetRivers), stake 2.82
Blend 49.7% vs market 47.2%, edge +6.4%. The 2.14 is the best of 5 books; the median is 2.00. If the market is right, EV is +1.0% at 2.14 and -5.6% at the median. The model alone has Nolan at only 40.4%, and Elo has Moicano at 60%; the "edge" exists because the blend leans toward the market.
For: no flags, full data (20 and 6 fights), and it is the largest stake. Answer: a 2.5-point gap on a coin-flip fight is smaller than the model's error, and it is 49% of the card's exposure on a price a UK bettor may not get.

## Mickey Gall at 3.65 (BetRivers), stake 1.58
Edge +8.4%, but flagged: a 715-day layoff and unknown opponent age. Blend 29.7% vs market 26.3%. Market-right EV is -4.2% at 3.65 and -10.8% at the median 3.40. Best-price underdog bets are where line shopping lost money (-10.0% to -18.4% on UK-reachable books). The market may know about camp and weight.
For: long odds pay well if right. Answer: the model's takedown-accuracy driver is offset by layoff and inactivity penalties, so it is unsure about a man who has not fought in two years.

## Theodor Berggren at 2.50 (Caesars), stake 0.91
Both fighters have 1 fight in the data (flagged thin), so the blend is mostly the odds. Edge +5.4%; market-right EV is -3.9% at 2.50 and -6.6% at the median 2.43. The stake is already cut for thin data, which concedes the problem.
For: the stake is under 1. Answer: it is small because the signal is weak; that argues for 0.

## Tainara Lisboa at 5.60 (Caesars), stake 0.46
Szabova is "not in the data", age unknown, so she is priced as a debutant. Edge +8.4% comes from 19.4% vs 15.5%; if the market is right, EV is -13.5% (0.1545 x 5.6 = 0.865). The 5.60 equals the median, so one book may be the only source.
For: a 5.6 payout. Answer: even if the model is right, the gain is about 0.04 on a 0.46 stake; a 4-point probability error on a longshot swings the edge enormously.

## Luana Santos, paper pick at 1.37 (Caesars), stake 10.0
Model alone 84.0% (tier 80+), but the blend is 74.2% vs market 71.2%, and the project's own rule rejects it as a bet: edge +1.7% against a 3% minimum. If the market is right, EV is -2.4% (0.7122 x 1.37 = 0.976). The 80+ result (+8.4% on 52 bets, range -4% to +20%) was found after the fact while scanning cutoffs from 70 to 90; in the earlier period it was +5.5% (range -3% to +13%), and at 85% only +1.4%. Forward test: 1 logged, 0 graded, 150 needed.
For: it replicated across two periods at +5% to +8%. Answer: both ranges include zero, the cutoff was selected from the data, and the pre-set rule needs about 40 more 80+ picks. A 10 stake is the cap, and a loss costs 10 against a win of 3.70.

## Overall
Every positive test number has a range that includes zero; the one resolved bucket (edges above 5%) loses.
The opening-line edge was gone by mid-week (+5.1% to -1.3%), so these prices likely carry no model skill.
Pass, or paper-track only; if staking anything, well under full Kelly's 5.77.
