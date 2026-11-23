# Phase 4 acceptance: skill components vs a division-average model

Held-out fighter-fights from 2015 on, everything as-of. Mean Poisson deviance (lower is better); the difference is skill model minus division average with a paired bootstrap 95% interval (negative = skills help).

| Target | n | Skill model | Division average | Difference [95% CI] | Verdict |
|---|---|---|---|---|---|
| Significant strikes landed | 9434 | 11.704 | 14.717 | -3.013 [-3.381, -2.648] | better |
| Takedowns landed | 9434 | 1.568 | 1.925 | -0.357 [-0.398, -0.316] | better |
| Knockdowns landed (power x chin, per head strike: the model's version) | 9434 | 0.992 | 1.006 | -0.015 [-0.022, -0.007] | better |
| Knockdowns landed (per-15 rate version, rejected) | 9434 | 1.039 | 1.006 | +0.033 [+0.014, +0.053] | not better |

Finishes (KO/TKO, submission, decision) are scored in `docs/phase8_simulator.md` against base rates. Posterior predictive checks (strike-total coverage by division) are there too.

# Skill trajectories for a sense check

Each fighter's opponent-adjusted skills as they stood going into their 3rd UFC bout, their middle bout, and their latest. Please tell me which look wrong; those are the ones to investigate.

## Jon Jones (24 bouts)

| Skill | 2009-07-11 | 2013-04-27 | 2024-11-16 |
|---|---|---|---|
| Elo | 1567.59 | 1808.94 | 1959.02 |
| Strike offence /15 | 39.59 | 72.21 | 63.51 |
| Strike defence (absorbed /15) | 35.12 | 20.51 | 36.27 |
| Power | 1.68 | 1.33 | 0.86 |
| Chin (KD taken per 100 head) | 1.51 | 1.16 | 0.87 |
| Takedown offence /15 | 3.60 | 2.39 | 1.81 |
| Takedown defence (absorbed /15) | 0.82 | 0.27 | 0.75 |
| Control s /15 | 264.24 | 363.60 | 202.84 |
| Sub attempts /15 | 0.47 | 1.31 | 0.69 |
| Cardio slope | 0.79 | 1.14 | 1.18 |

## Khabib Nurmagomedov (13 bouts)

| Skill | 2013-01-19 | 2016-04-16 | 2020-10-24 |
|---|---|---|---|
| Elo | 1572.86 | 1684.68 | 1843.84 |
| Strike offence /15 | 37.29 | 45.45 | 61.59 |
| Strike defence (absorbed /15) | 29.97 | 29.39 | 24.00 |
| Power | 1.42 | 1.15 | 0.68 |
| Chin (KD taken per 100 head) | 1.26 | 1.07 | 0.90 |
| Takedown offence /15 | 2.22 | 6.39 | 5.51 |
| Takedown defence (absorbed /15) | 0.72 | 0.64 | 0.48 |
| Control s /15 | 384.88 | 437.87 | 586.11 |
| Sub attempts /15 | 0.85 | 0.76 | 0.85 |
| Cardio slope | 0.86 | 0.97 | 1.09 |

## Israel Adesanya (19 bouts)

| Skill | 2018-07-06 | 2021-03-06 | 2026-03-28 |
|---|---|---|---|
| Elo | 1561.77 | 1804.21 | 1702.68 |
| Strike offence /15 | 57.76 | 60.18 | 64.34 |
| Strike defence (absorbed /15) | 38.41 | 27.39 | 38.24 |
| Power | 1.16 | 1.98 | 1.00 |
| Chin (KD taken per 100 head) | 1.02 | 0.77 | 0.86 |
| Takedown offence /15 | 0.86 | 0.37 | 0.44 |
| Takedown defence (absorbed /15) | 2.35 | 0.81 | 1.20 |
| Control s /15 | 100.66 | 66.91 | 74.27 |
| Sub attempts /15 | 0.30 | 0.55 | 0.22 |
| Cardio slope | 0.82 | 1.53 | 1.30 |

## Alex Pereira (13 bouts)

| Skill | 2022-07-02 | 2023-11-11 | 2026-06-14 |
|---|---|---|---|
| Elo | 1569.80 | 1687.78 | 1791.52 |
| Strike offence /15 | 72.26 | 87.13 | 82.56 |
| Strike defence (absorbed /15) | 44.44 | 46.05 | 42.58 |
| Power | 1.04 | 1.00 | 1.29 |
| Chin (KD taken per 100 head) | 0.87 | 0.90 | 0.78 |
| Takedown offence /15 | 0.55 | 0.51 | 0.44 |
| Takedown defence (absorbed /15) | 2.02 | 2.16 | 1.27 |
| Control s /15 | 112.50 | 60.22 | 64.31 |
| Sub attempts /15 | 0.33 | 0.53 | 0.44 |
| Cardio slope | 1.24 | 1.53 | 1.47 |

## Islam Makhachev (19 bouts)

| Skill | 2016-09-17 | 2021-07-17 | 2026-08-15 |
|---|---|---|---|
| Elo | 1504.36 | 1720.41 | 1949.54 |
| Strike offence /15 | 47.91 | 34.44 | 40.89 |
| Strike defence (absorbed /15) | 35.89 | 20.69 | 21.66 |
| Power | 1.09 | 1.10 | 0.91 |
| Chin (KD taken per 100 head) | 1.38 | 1.00 | 0.88 |
| Takedown offence /15 | 2.62 | 2.72 | 2.65 |
| Takedown defence (absorbed /15) | 1.14 | 0.49 | 0.44 |
| Control s /15 | 241.69 | 470.37 | 513.92 |
| Sub attempts /15 | 0.98 | 1.10 | 0.86 |
| Cardio slope | 1.00 | 1.53 | 1.48 |

## Conor McGregor (15 bouts)

| Skill | 2014-07-19 | 2016-03-05 | 2026-07-11 |
|---|---|---|---|
| Elo | 1571.35 | 1740.29 | 1700.78 |
| Strike offence /15 | 49.99 | 68.85 | 59.25 |
| Strike defence (absorbed /15) | 29.75 | 37.24 | 51.41 |
| Power | 1.31 | 1.88 | 1.00 |
| Chin (KD taken per 100 head) | 1.21 | 1.02 | 0.91 |
| Takedown offence /15 | 2.49 | 1.83 | 1.17 |
| Takedown defence (absorbed /15) | 1.31 | 1.72 | 1.48 |
| Control s /15 | 342.19 | 261.11 | 165.42 |
| Sub attempts /15 | 0.50 | 0.35 | 0.53 |
| Cardio slope | 0.84 | 0.90 | 1.06 |

## Georges St-Pierre (22 bouts)

| Skill | 2004-10-22 | 2008-04-19 | 2017-11-04 |
|---|---|---|---|
| Elo | 1563.98 | 1725.44 | 1912.96 |
| Strike offence /15 | 48.15 | 67.65 | 55.49 |
| Strike defence (absorbed /15) | 14.84 | 19.03 | 25.71 |
| Power | 1.92 | 1.51 | 0.99 |
| Chin (KD taken per 100 head) | 1.59 | 1.80 | 1.08 |
| Takedown offence /15 | 3.60 | 4.40 | 3.70 |
| Takedown defence (absorbed /15) | 0.60 | 0.63 | 0.66 |
| Control s /15 | 500.85 | 625.96 | 406.27 |
| Sub attempts /15 | 0.56 | 2.00 | 0.72 |
| Cardio slope | 1.19 | 1.38 | 1.10 |

## Anderson Silva (25 bouts)

| Skill | 2007-02-03 | 2011-02-05 | 2020-10-31 |
|---|---|---|---|
| Elo | 1590.13 | 1815.02 | 1648.32 |
| Strike offence /15 | 62.92 | 50.98 | 46.09 |
| Strike defence (absorbed /15) | 26.56 | 21.82 | 40.92 |
| Power | 2.36 | 2.31 | 1.09 |
| Chin (KD taken per 100 head) | 1.64 | 1.18 | 1.15 |
| Takedown offence /15 | 1.59 | 0.91 | 0.62 |
| Takedown defence (absorbed /15) | 1.46 | 0.75 | 1.16 |
| Control s /15 | 274.62 | 141.22 | 89.54 |
| Sub attempts /15 | 0.89 | 0.82 | 0.37 |
| Cardio slope | 1.00 | 1.36 | 1.37 |

## Valentina Shevchenko (19 bouts)

| Skill | 2016-07-23 | 2020-02-08 | 2025-11-15 |
|---|---|---|---|
| Elo | 1504.66 | 1670.16 | 1787.00 |
| Strike offence /15 | 33.15 | 54.85 | 47.09 |
| Strike defence (absorbed /15) | 24.29 | 25.15 | 26.42 |
| Power | 1.03 | 0.91 | 0.76 |
| Chin (KD taken per 100 head) | 1.05 | 0.94 | 0.84 |
| Takedown offence /15 | 2.19 | 2.47 | 3.58 |
| Takedown defence (absorbed /15) | 1.68 | 0.58 | 0.79 |
| Control s /15 | 233.83 | 298.34 | 367.52 |
| Sub attempts /15 | 0.21 | 0.46 | 0.45 |
| Cardio slope | 1.12 | 1.22 | 1.22 |

## Charles Oliveira (37 bouts)

| Skill | 2010-12-11 | 2017-12-02 | 2026-03-07 |
|---|---|---|---|
| Elo | 1569.53 | 1605.04 | 1810.56 |
| Strike offence /15 | 44.30 | 48.77 | 55.05 |
| Strike defence (absorbed /15) | 24.68 | 42.65 | 44.11 |
| Power | 1.44 | 1.03 | 1.02 |
| Chin (KD taken per 100 head) | 1.44 | 0.91 | 1.03 |
| Takedown offence /15 | 2.40 | 3.29 | 2.29 |
| Takedown defence (absorbed /15) | 1.56 | 1.18 | 0.72 |
| Control s /15 | 205.42 | 284.22 | 431.54 |
| Sub attempts /15 | 2.25 | 2.14 | 2.01 |
| Cardio slope | 1.27 | 1.00 | 1.01 |
