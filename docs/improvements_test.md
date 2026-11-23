# Improvements test: stat padding and opponent quality

Development folds 2015 to 2025-10-25 (5256 decisive bouts). Current model groups: style_interactions, age_growth, record. Each improvement is added on its own, then all four together. Difference = new minus current log loss with a paired bootstrap 95% interval; negative is better.

| Model | Added | Log loss | Difference [95% CI] | Verdict |
|---|---|---|---|---|
| lr | (current) | 0.6523 | | |
| lr | acc_adjusted | 0.6517 | -0.0006 [-0.0020, +0.0008] | no clear effect |
| lr | elo2 | 0.6498 | -0.0024 [-0.0043, -0.0005] | helps |
| lr | joint_adj | 0.6497 | -0.0025 [-0.0054, +0.0005] | no clear effect |
| lr | quality | 0.6495 | -0.0027 [-0.0052, -0.0003] | helps |
| lr | all four | 0.6454 | -0.0069 [-0.0111, -0.0027] | helps |
| lgbm | (current) | 0.6551 | | |
| lgbm | acc_adjusted | 0.6546 | -0.0005 [-0.0026, +0.0017] | no clear effect |
| lgbm | elo2 | 0.6533 | -0.0018 [-0.0035, -0.0001] | helps |
| lgbm | joint_adj | 0.6524 | -0.0027 [-0.0052, -0.0001] | helps |
| lgbm | quality | 0.6527 | -0.0024 [-0.0046, -0.0001] | helps |
| lgbm | all four | 0.6499 | -0.0052 [-0.0086, -0.0018] | helps |

## Ratings on their own

Elo log loss 0.6819; Elo2 (margin of victory + rating deviation) 0.6781; difference -0.0038 [-0.0065, -0.0011].

## Decision

- acc_adjusted: no clear gain on top of the current model
- elo2: passes the add-on test; goes into the group selection
- joint_adj: passes the add-on test; goes into the group selection
- quality: passes the add-on test; goes into the group selection

The final choice is made by rerunning the greedy group selection with every group available (config/feature_groups.json), so a group that only helps alongside others can still be picked.
