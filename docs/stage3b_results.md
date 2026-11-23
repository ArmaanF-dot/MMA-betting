# Stage 3 follow-up: robustness of H3 and the H4 strategy

## A. H3 robustness

| Period | Check | Coefficient [95%] |
|---|---|---|
| 2015-2021 | model, the pre-set formula (x = model - open) | +0.1698 [+0.1413, +0.1984] |
| 2015-2021 | free open: coefficient on logit(model) | +0.2513 [+0.2243, +0.2783] |
| 2015-2021 | free open: coefficient on logit(open) (drift back) | -0.0755 [-0.1081, -0.0430] |
| 2015-2021 | placebo: constant 50% model (x = -logit(open)) | -0.0711 [-0.0954, -0.0468] |
| 2015-2021 | placebo: Elo probability | -0.0425 [-0.0706, -0.0144] |
| 2015-2021 | placebo: model shuffled across bouts | -0.0386 [-0.0541, -0.0232] |
| 2022-2025 | model, the pre-set formula (x = model - open) | +0.1653 [+0.1275, +0.2031] |
| 2022-2025 | free open: coefficient on logit(model) | +0.2914 [+0.2512, +0.3316] |
| 2022-2025 | free open: coefficient on logit(open) (drift back) | -0.0825 [-0.1199, -0.0450] |
| 2022-2025 | placebo: constant 50% model (x = -logit(open)) | -0.0917 [-0.1174, -0.0659] |
| 2022-2025 | placebo: Elo probability | -0.0737 [-0.1021, -0.0454] |
| 2022-2025 | placebo: model shuffled across bouts | -0.0480 [-0.0667, -0.0293] |

## B. H4 strategy on validation fights with per-book prices

1150 fights. Mean |p_H4 - market| = 0.0164; fights where p_H4 differs from the market by more than 2 points: 32%.

| Probability used | Price | Bets | Profit | Return [95%, events as units] | Mean closing-line value |
|---|---|---|---|---|---|
| H4 | best | 428 | +47 | +1.1% [-11.4%, +13.3%] | +0.0301 |
| H4 | median | 111 | -128 | -11.5% [-34.8%, +15.4%] | -0.0448 |
| market only (line shopping) | best | 188 | -232 | -12.4% [-35.5%, +11.3%] | +0.0914 |
| market only (line shopping) | median | 0 | | | |
