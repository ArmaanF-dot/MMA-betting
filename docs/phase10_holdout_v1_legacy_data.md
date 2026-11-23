# Locked holdout, scored once (2022-09-17 to the end of the data)

Decisive bouts: 526; with odds: 452. Reported as is. Blend weight w = 0.1.

| Model | n | Log loss | Brier | Accuracy | AUC | ECE |
|---|---|---|---|---|---|---|
| Coin flip | 526 | 0.6931 | 0.2500 | 0.481 | 0.500 | 0.063 |
| B1 Elo | 526 | 0.6812 | 0.2442 | 0.549 | 0.583 | 0.069 |
| B2 logistic | 526 | 0.6482 | 0.2285 | 0.605 | 0.665 | 0.040 |
| B3 LightGBM | 526 | 0.6521 | 0.2303 | 0.608 | 0.658 | 0.065 |
| Stack (no market) | 526 | 0.6491 | 0.2289 | 0.612 | 0.664 | 0.046 |
| B0 market (Shin) | 452 | 0.6120 | 0.2122 | 0.673 | 0.719 | 0.040 |
| Blend with market | 452 | 0.6118 | 0.2120 | 0.675 | 0.721 | 0.041 |

Paired bootstrap on bouts with odds (positive = first is worse):

- Blend with market minus B0 market: -0.0003 [-0.0031, +0.0024]
- Stack (no market) minus B0 market: +0.0392 [+0.0115, +0.0661]

The holdout is a single fold, so the betting simulation is not repeated here.