# Stage 2 results (development period only)

## 2.1 The model against the market of record

| Period | Model | Bouts | Model log loss | Market log loss | Model minus market [95%] |
|---|---|---|---|---|---|
| 2015-2021 | lr | 3101 | 0.6492 | 0.6203 | +0.0289 [+0.0185, +0.0387] |
| 2015-2021 | stack | 2201 | 0.6477 | 0.6153 | +0.0324 [+0.0210, +0.0437] |
| 2022-2025 | lr | 1822 | 0.6299 | 0.5972 | +0.0327 [+0.0205, +0.0453] |
| 2022-2025 | stack | 1822 | 0.6309 | 0.5972 | +0.0337 [+0.0215, +0.0462] |
| 2015-2025 | lr | 4923 | 0.6421 | 0.6118 | +0.0303 [+0.0224, +0.0380] |
| 2015-2025 | stack | 4023 | 0.6401 | 0.6071 | +0.0330 [+0.0244, +0.0413] |

By source of the closing price (logistic model, 2015-2025):

- old: 146 bouts, model minus market +0.0503 [+0.0036, +0.0953]
- range: 3627 bouts, model minus market +0.0276 [+0.0186, +0.0366]
- books: 1150 bouts, model minus market +0.0363 [+0.0200, +0.0520]

## H2 Favourite-longshot bias: slope of result on logit(market fair probability); above 1 means favourites are underpriced

| Price | Period | Bouts | Slope [95%] |
|---|---|---|---|
| close | discovery 2015-2021 | 3101 | 1.079 [0.966, 1.191] |
| close | validation 2022-2025 | 1822 | 1.156 [1.042, 1.292] |
| open | discovery 2015-2021 | 3013 | 1.099 [0.955, 1.239] |
| open | validation 2022-2025 | 1715 | 1.226 [1.073, 1.383] |

- close: kept = False (discovery [0.966, 1.191], validation [1.042, 1.292], needs both intervals on the same side of 1)
- open: kept = False (discovery [0.955, 1.239], validation [1.073, 1.383], needs both intervals on the same side of 1)

## H1 Line shopping against the leave-one-out consensus (per-book data, 2023-06 to 2025-10-24)

1145 fights with 4+ books (so each leave-one-out consensus has 3+).

| Venue | Threshold | Bets | Profit | Return [95%, events as units] | Mean closing-line value |
|---|---|---|---|---|---|
| all books | 2% | 395 | -396 | -10.0% [-24.3%, +3.9%] | +0.053 |
| all books | 4% | 188 | -231 | -12.3% [-35.5%, +13.0%] | +0.089 |
| UK-reachable books | 2% | 101 | -186 | -18.4% [-43.8%, +10.9%] | +0.072 |
| UK-reachable books | 4% | 45 | -24 | -5.3% [-51.9%, +51.0%] | +0.134 |
| exchange 2% commission | 2% | 395 | -658 | -16.7% [-29.7%, -3.8%] | -0.010 |
| exchange 2% commission | 4% | 188 | -411 | -21.9% [-42.1%, +0.7%] | -0.010 |
| exchange 5% commission | 2% | 395 | -723 | -18.3% [-31.0%, -5.7%] | -0.010 |
| exchange 5% commission | 4% | 188 | -441 | -23.5% [-43.2%, -1.4%] | -0.010 |

H1 kept (sportsbook venues, validation interval above zero for a fixed threshold): False.
The exchange rows price the same selected sides at the consensus fair price (an assumption): they show what the costs alone do, not a tradable price.