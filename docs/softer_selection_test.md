# Softer feature selection and age x style curves

Groups chosen on the 2015-2021 folds only; scored on 2022-01-01 to 2025-10-25 (1947 decisive bouts). Difference = configuration minus current, paired bootstrap 95% interval; negative is better.

Relaxed greedy picked (selection period): joint_adj, age_style, elo2, record, grappling, acc_adjusted, physical. Steps: joint_adj 0.6670 (+0.0261); age_style 0.6569 (+0.0101); elo2 0.6522 (+0.0047); record 0.6503 (+0.0019); grappling 0.6494 (+0.0009); acc_adjusted 0.6483 (+0.0011); physical 0.6475 (+0.0008); durability 0.6472 (+0.0003)

| Configuration | Log loss (scoring period) | Difference vs current [95% CI] | Verdict |
|---|---|---|---|
| current (hard rule, 3 groups) | 0.6410 | | |
| current + age_style | 0.6408 | -0.0002 [-0.0022, +0.0018] | no clear difference |
| relaxed greedy (7 groups) | 0.6366 | -0.0043 [-0.0105, +0.0021] | no clear difference |
| all groups, ridge | 0.6338 | -0.0072 [-0.0135, -0.0011] | better |
| all groups, LightGBM | 0.6402 | -0.0008 [-0.0058, +0.0045] | no clear difference |
| current, LightGBM | 0.6441 | +0.0031 [-0.0004, +0.0066] | no clear difference |

Adopt: all groups, ridge.
