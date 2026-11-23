# UFC fight prediction model

Calibrated win, method and round probabilities for UFC bouts, benchmarked against de-vigged market odds. Built to the
"UFC Fight Prediction Model: Build Spec". Paper trading only: nothing here places or recommends a real bet.

## One command per stage

```
pip install -e .[dev]
python -m ufcmodel update          # refresh the per-round CSVs from GitHub, convert, load, run quality checks
make data                          # same pipeline from the files already in data/raw
python -m ufcmodel phase10         # B2/B3, simulator, stack, market blend, ablation, betting sim  (about 15 minutes)
python -m ufcmodel holdout         # scores the locked holdout ONCE (refuses to run twice)
python -m ufcmodel skills          # Phase 4 acceptance and skill sheet for well-known fighters
python -m ufcmodel styles          # Phase 5 report and the label template for you to fill
python -m ufcmodel fightweek cards/next.csv --out docs/fightweek.html
python -m pytest -q
```

Card file columns: `date,fighter_a,fighter_b,weight_class,odds_a,odds_b` (odds optional) and optionally `rounds` (3 or 5).

## Where things are

- `src/ufcmodel/ingest`: converters, loader, update. `qa`: data quality checks. `features/asof.py`: the as-of feature store.
- `ratings` (Elo), `styles` (archetypes), `judging` (round scoring), `sim` (simulator), `eval` (walk-forward, ablation, reports),
  `betting` (paper-trade log and gate), `tagging` (tag import, kappa, cross-check), `reports` (fight-week HTML).
- `tools/tagger.html`: the hand-tagging tool (Armaan). `docs/tagging_guide.md` explains it.
- `docs/decisions.md` is the decision log and every phase's results note. `docs/data_dictionary.md` describes the tables.

## Rules the code keeps

No leakage (tested), probabilities not picks, the market as the benchmark, every feature group earns its place in the ablation,
shrinkage everywhere, fixed seeds, respect for data rights (local copies only, rate-limited, never redistributed, no bot-check
bypassing), paper first, honest reporting. Scraped data is git-ignored.
