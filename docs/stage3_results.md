# Stage 3 results (development period only)

4923 decisive bouts with a closing price and a model prediction: discovery 3101, validation 1822.

## H3 Does the model predict the opening-to-closing move?

| Period | Bouts | Coefficient on x = logit(model) - logit(open) [95%] | R^2 of the move |
|---|---|---|---|
| discovery 2015-2021 | 3013 | +0.1698 [+0.1413, +0.1984] | 0.0800 |
| validation 2022-2025 | 1715 | +0.1653 [+0.1275, +0.2031] | 0.0653 |

H3 kept (coefficient above zero with the interval excluding zero in both periods): True.

Which of the H4 features predict the move (all bouts 2015-2025, standardised coefficients on the closing move, clustered by event)?

| Feature | Coefficient (per 1 sd) [95%] |
|---|---|
| age diff | -0.0984 [-0.1108, -0.0860] |
| aged 35+ | -0.0111 [-0.0231, +0.0009] |
| layoff 1y+ | +0.0006 [-0.0086, +0.0097] |
| last fight KO loss | -0.0130 [-0.0253, -0.0008] |
| KO losses in last 3 | -0.0094 [-0.0220, +0.0033] |
| padding index | +0.0223 [+0.0115, +0.0330] |
| win streak 3+ | +0.0202 [+0.0115, +0.0288] |
| debut | -0.0191 [-0.0298, -0.0085] |
| late matchup x market | +0.0315 [+0.0204, +0.0427] |
| reach diff | +0.0242 [+0.0149, +0.0335] |
| model gap | -0.1258 [-0.1374, -0.1141] |

Strategy rows (only because H3 was kept): predicted move toward a side above 0.05 logit, bet at the opening price.
- validation 2022-2025: 1048 bets, return +5.0% [-2.4%, +12.8%], mean closing-line value -0.0153

## H4 Market-residual model (offset = logit of the closing market probability)

11 features: ridge lambda 300; validation log loss 0.5947 vs market 0.5972; model minus market -0.0026 [-0.0047, -0.0004] (1822 bouts)

| Feature | Coefficient on the log-odds, per 1 sd (discovery fit) |
|---|---|
| age diff | -0.0494 |
| aged 35+ | -0.0065 |
| layoff 1y+ | -0.0168 |
| last fight KO loss | -0.0101 |
| KO losses in last 3 | -0.0078 |
| padding index | +0.0134 |
| win streak 3+ | -0.0030 |
| debut | -0.0259 |
| late matchup x market | +0.0526 |
| reach diff | +0.0345 |
| model gap | +0.0523 |

H4 kept (validation log loss beats the market, interval below zero): True.

Same model without the 'model gap' feature (is the model adding anything, or only the other 10?):
10 features, no model gap: ridge lambda 300; validation log loss 0.5951 vs market 0.5972; model minus market -0.0022 [-0.0041, -0.0003] (1822 bouts)

## H5 Residual momentum (past sum of result minus market probability, shrunk by fight count)

| Period | Bouts | Coefficient on logit scale, per 1 sd [95%, events bootstrap] |
|---|---|---|
| discovery 2015-2021 | 3101 | -0.0707 [-0.1332, -0.0023] |
| validation 2022-2025 | 1822 | -0.0137 [-0.0996, +0.0671] |

H5 kept (interval excludes zero in both periods, same sign): False.

As a 12th feature of H4:
12 features: ridge lambda 300; validation log loss 0.5946 vs market 0.5972; model minus market -0.0026 [-0.0048, -0.0004] (1822 bouts)

Survivors: H3 True, H4 True, H5 False.