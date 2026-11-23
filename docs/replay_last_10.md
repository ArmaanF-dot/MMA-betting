# Replay of recent events (each predicted using only data before it)

| Event | Date | Bouts | Winners right | Log loss | Elo log loss |
|---|---|---|---|---|---|
| UFC 333: Volkanovski vs. Evloev | 2026-10-24 | 14 | 9 | 0.693 | 0.638 |
| UFC Fight Night: Buckley vs. Malott | 2026-10-17 | 13 | 7 | 0.813 | 0.718 |
| UFC Fight Night: Allen vs. Duncan | 2026-10-10 | 11 | 4 | 0.776 | 0.740 |
| UFC 332: Silva vs. Wang | 2026-10-03 | 14 | 12 | 0.513 | 0.692 |
| UFC Fight Night: Rosas Jr. vs. Barcelos | 2026-09-26 | 12 | 9 | 0.593 | 0.681 |
| UFC 331: Van vs. Pantoja 2 | 2026-09-19 | 12 | 6 | 0.753 | 0.686 |
| Noche UFC: Silva vs. Delgado | 2026-09-12 | 13 | 8 | 0.600 | 0.756 |
| UFC Fight Night: Hooker vs. Parnasse | 2026-09-05 | 14 | 7 | 0.707 | 0.815 |
| UFC Fight Night: Nurmagomedov vs. Song | 2026-08-29 | 13 | 10 | 0.566 | 0.640 |
| UFC Fight Night: Hernandez vs. Rodrigues | 2026-08-22 | 13 | 6 | 0.707 | 0.694 |

**All 129 bouts:** winners right 78 (60.5%); log loss 0.670 (coin flip 0.693, Elo 0.706, the model's long-run average about 0.64); Brier 0.238 (coin flip 0.250).

With 129 bouts a coin flip would be right between 41% and 59% of the time, so accuracy alone can't separate skill from luck here.

By how confident the model was:

| Model's confidence in its pick | Bouts | Picked right | Average confidence |
|---|---|---|---|
| 50% to 60% | 56 | 33 (59%) | 55% |
| 60% to 70% | 48 | 28 (58%) | 64% |
| 70% to 100% | 25 | 17 (68%) | 76% |

Method: average probability given to the winner and method that happened 20% (a blind guess among six is 17%). Went the distance: 42 of 128 (33%); the model expected 55.7 (43%).
