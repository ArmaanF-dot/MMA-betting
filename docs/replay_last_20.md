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
| UFC 330: Makhachev vs. Machado Garry | 2026-08-15 | 12 | 6 | 0.812 | 0.744 |
| UFC Fight Night: Gamrot vs. Salkilld | 2026-08-08 | 12 | 11 | 0.499 | 0.657 |
| UFC Fight Night: Medic vs. Rodriguez | 2026-08-01 | 14 | 10 | 0.627 | 0.712 |
| UFC Fight Night: Ankalaev vs. Guskov | 2026-07-25 | 12 | 7 | 0.727 | 0.654 |
| UFC Fight Night: Du Plessis vs. Usman | 2026-07-18 | 12 | 11 | 0.461 | 0.642 |
| UFC 329: McGregor vs. Holloway 2 | 2026-07-11 | 14 | 10 | 0.603 | 0.602 |
| UFC Fight Night: Fiziev vs. Torres | 2026-06-27 | 13 | 8 | 0.694 | 0.644 |
| UFC Fight Night: Kape vs. Horiguchi | 2026-06-20 | 12 | 9 | 0.589 | 0.752 |
| UFC Freedom 250 | 2026-06-14 | 7 | 6 | 0.537 | 0.667 |
| UFC Fight Night: Muhammad vs. Bonfim | 2026-06-06 | 12 | 9 | 0.599 | 0.620 |

**All 249 bouts:** winners right 165 (66.3%); log loss 0.645 (coin flip 0.693, Elo 0.688, the model's long-run average about 0.64); Brier 0.226 (coin flip 0.250).

With 249 bouts a coin flip would be right between 44% and 56% of the time, so accuracy alone can't separate skill from luck here.

By how confident the model was:

| Model's confidence in its pick | Bouts | Picked right | Average confidence |
|---|---|---|---|
| 50% to 60% | 108 | 71 (66%) | 55% |
| 60% to 70% | 88 | 57 (65%) | 64% |
| 70% to 100% | 53 | 37 (70%) | 76% |

Method: average probability given to the winner and method that happened 21% (a blind guess among six is 17%). Went the distance: 81 of 248 (33%); the model expected 112.3 (45%).
