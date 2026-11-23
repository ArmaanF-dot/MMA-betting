.PHONY: update data convert load qa test backtest select-groups phase10 holdout skills styles fightweek
# refresh the per-round CSVs from GitHub, convert, load, run quality checks
update:
	python -m ufcmodel update
# the same pipeline from the files already in data/raw
data: convert load qa
convert:
	python -m ufcmodel convert
load:
	python -m ufcmodel load data/raw/csv
qa:
	python -m ufcmodel qa
test:
	python -m pytest -q
# greedy feature-group selection (writes config/feature_groups.json), then the full evaluation (about 30 minutes in all)
select-groups:
	python -m ufcmodel select-groups
phase10:
	python -m ufcmodel phase10
# scores the locked holdout ONCE; refuses to overwrite docs/phase10_holdout.md
holdout:
	python -m ufcmodel holdout
skills:
	python -m ufcmodel skills
styles:
	python -m ufcmodel styles
fightweek:
	python -m ufcmodel fightweek $(CARD) --out docs/fightweek.html
# legacy Elo-vs-odds baseline on the older dataset: python -m ufcmodel convert-legacy, then the old backtest module
