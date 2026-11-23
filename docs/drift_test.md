# Finish-rate drift test

Development folds 2015-01-01 to 2025-10-25; last fold = 2025-01-01 onward. Differences are against the current setting (paired bootstrap, negative is better).

| Variant | Round of finish | Goes the distance | Winner x method | Distance: expected vs actual (all) | Distance: expected vs actual (last fold) |
|---|---|---|---|---|---|
| current (last 1200 bouts, equal weight) | 1.2067 | 0.6724 | 1.6315 | 50.4% vs 50.4% | 53.1% vs 50.6% |
| half-life 730 days, 1200 bouts | 1.2076 (+0.0009 [-0.0016, +0.0034]) | 0.6735 (+0.0010 [-0.0005, +0.0025]) | 1.6337 (+0.0022 [-0.0009, +0.0053]) | 50.0% vs 50.4% | 53.9% vs 50.6% |
| half-life 365 days, 1200 bouts | 1.2079 (+0.0012 [-0.0014, +0.0040]) | 0.6733 (+0.0008 [-0.0009, +0.0025]) | 1.6330 (+0.0015 [-0.0017, +0.0048]) | 49.8% vs 50.4% | 54.3% vs 50.6% |
| half-life 365 days, 2400 bouts | 1.2077 (+0.0010 [-0.0017, +0.0037]) | 0.6738 (+0.0014 [-0.0003, +0.0031]) | 1.6314 (-0.0001 [-0.0032, +0.0031]) | 49.9% vs 50.4% | 54.4% vs 50.6% |
| half-life 180 days, 2400 bouts | 1.2122 (+0.0055 [+0.0026, +0.0085]) | 0.6763 (+0.0039 [+0.0017, +0.0060]) | 1.6353 (+0.0037 [+0.0002, +0.0074]) | 49.4% vs 50.4% | 55.1% vs 50.6% |

Adopt: nothing; the current calibration stands.
