# Phase 5: style system

Each fighter-bout has 16 as-of style axes (opponent-adjusted, shrunk to the global rate): dist_share, clinch_share, ground_share, leg_share, body_share, sig_for, power, td_for, ctrl_for, ground_per_ctrl, sub_for, rev_for, sig_def, td_def, pace_slope, sig_acc.

## Discovered styles (diagonal Gaussian mixture, 6 components, fit once on pre-2015 bouts)

- Style 0 (weight 20%): low sig_for (-0.8 sd), high sub_for (+0.7 sd), high rev_for (+0.6 sd)
- Style 1 (weight 25%): low sig_acc (-0.6 sd), high dist_share (+0.6 sd), low ground_share (-0.5 sd)
- Style 2 (weight 15%): high dist_share (+1.4 sd), low ground_share (-1.2 sd), high sig_for (+1.0 sd)
- Style 3 (weight 19%): low td_for (-0.6 sd), high clinch_share (+0.5 sd), high power (+0.4 sd)
- Style 4 (weight 6%): high ground_share (+1.8 sd), low dist_share (-1.7 sd), low sig_def (-1.3 sd)
- Style 5 (weight 16%): high ctrl_for (+1.4 sd), high td_for (+1.3 sd), high ground_share (+1.0 sd)

## Stability

Bootstrap refits (20) on 1952 pre-2015 fighter snapshots: mean adjusted Rand index vs the reference clustering 0.53 (worst 0.36). Agreement between the mixture and NMF clustering: 0.08. 1.0 would be identical partitions; these are moderate, so treat style weights as soft descriptions, not hard labels.

## Interaction terms and the ablation

Groups tested in the ablation (docs/phase10_evaluation.md): style_axes (d_leg_share, d_body_share, d_dist_share, d_clinch_share, d_ground_share), style_interactions (td_matchup, str_matchup, ctrl_matchup) and style_matrix (the 15 antisymmetric terms s_A[i] s_B[j] - s_A[j] s_B[i]). Each stays only if its interval is above zero there; the decisions are logged in docs/decisions.md.

## Not done

- Matching clusters to the 16 named archetypes and the semi-supervised placement need Armaan's labels for about 50 fighters: `docs/style_labels_template.csv` is ready with the model's own weights for the 50 fighters with the most bouts and a blank column to fill.
- Tag-only axes (takedown setup, entry type, pressure vs counter, weapon mix) and the habits catalogue need the tagging programme.
