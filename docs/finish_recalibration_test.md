# Finish recalibration test

Development folds 2015 to 2025-10-25. Simulator variants differ only in how the finish scalars are calibrated. Differences are against the current setting (paired bootstrap, negative is better).

| Variant | 6-class winner x method | Round of finish | Goes the distance | ECE (distance) | Expected vs actual distance rate |
|---|---|---|---|---|---|
| current (last 300 bouts) | 1.6399 | 1.2136 | 0.6824 | 0.023 | 49.5% vs 50.4% |
| last 150 bouts | 1.6457 (+0.0058 [+0.0021, +0.0096]) | 1.2208 (+0.0072 [+0.0037, +0.0108]) | 0.6868 (+0.0043 [+0.0020, +0.0067]) | 0.036 | 48.0% vs 50.4% |
| 300 + division multipliers | 1.6295 (-0.0103 [-0.0135, -0.0071]) | 1.2031 (-0.0105 [-0.0138, -0.0075]) | 0.6722 (-0.0102 [-0.0133, -0.0072]) | 0.016 | 50.9% vs 50.4% |
| 150 + division multipliers | 1.6316 (-0.0082 [-0.0126, -0.0040]) | 1.2059 (-0.0077 [-0.0120, -0.0036]) | 0.6721 (-0.0103 [-0.0135, -0.0073]) | 0.014 | 50.3% vs 50.4% |

Adopt: 150 + division multipliers (needs both round-of-finish and goes-the-distance log loss to improve, each with an interval below zero).
