import argparse
import sys

from ufcmodel.config import ROOT, load_config
from ufcmodel.db import connect
from ufcmodel.ingest.load_csv import load_csv_dir
from ufcmodel.qa.checks import report, run_checks


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ufcmodel")
    sub = p.add_subparsers(dest="cmd", required=True)
    ld = sub.add_parser("load", help="load per-table CSVs into the database")
    ld.add_argument("directory")
    sub.add_parser("qa", help="run data quality checks")
    sub.add_parser("backtest", help="walk-forward Elo vs de-vigged odds; writes docs/phase3_baseline_report.md")
    p10 = sub.add_parser("phase10", help="B2/B3, stack, blend, ablation, betting sim; writes docs/phase10_evaluation.md")
    p10.add_argument("--no-ablation", action="store_true")
    ho = sub.add_parser("holdout", help="score the locked holdout ONCE; refuses to overwrite docs/phase10_holdout.md")
    ho.add_argument("--force", action="store_true")
    sub.add_parser("select-groups", help="greedy forward selection of feature groups; writes config/feature_groups.json")
    ec = sub.add_parser("event-check", help="replay a past event using only earlier data and compare with the results")
    ec.add_argument("event", nargs="?", help="part of the event name, e.g. \"UFC 333\"")
    ec.add_argument("--last", type=int, help="replay the last N events instead and summarise them")
    sub.add_parser("styles", help="Phase 5 report and the style label template")
    sub.add_parser("skills", help="Phase 4 acceptance report and skill sheet for well-known fighters")
    sub.add_parser("update", help="refresh the Greco1899 CSVs from GitHub, then convert, load and QA")
    fw = sub.add_parser("fightweek", help="HTML report for a card CSV (date,fighter_a,fighter_b,weight_class,odds_a,odds_b)")
    fw.add_argument("card")
    fw.add_argument("--out", default="docs/fightweek.html")
    it = sub.add_parser("import-tags", help="load tagger.html JSON exports into the tags table")
    it.add_argument("directory", nargs="?", default="data/tags")
    it.add_argument("--pass-no", type=int, default=1)
    cv = sub.add_parser("convert", help="convert the Greco1899 per-round download (+ older odds file) into per-table CSVs")
    cv.add_argument("src", nargs="?", default="data/raw/greco")
    cv.add_argument("out", nargs="?", default="data/raw/csv")
    cl = sub.add_parser("convert-legacy", help="convert the older jansen88/ufc-data download (no per-round data)")
    cl.add_argument("src", nargs="?", default="data/raw/ufc_dataset")
    cl.add_argument("out", nargs="?", default="data/raw/csv_legacy")
    args = p.parse_args(argv)

    if args.cmd == "convert":
        from ufcmodel.ingest.convert_greco import convert
        for k, v in convert(args.src, args.out, "data/raw/ufc_dataset/odds_raw.csv", "data/interim").items():
            print(f"{k}: {v}")
        return 0
    if args.cmd == "update":
        from ufcmodel.ingest.update import update
        return update()
    if args.cmd == "convert-legacy":
        from ufcmodel.ingest.convert_ufc_data import convert
        for k, v in convert(args.src, args.out, "data/interim").items():
            print(f"{k}: {v}")
        return 0

    cfg = load_config()
    con = connect(ROOT / cfg["database"])
    if args.cmd == "backtest":
        from ufcmodel.eval.backtest import run
        print(run(con, ROOT / "docs" / "phase3_baseline_report.md"))
        return 0
    if args.cmd == "select-groups":
        from ufcmodel.eval.phase10 import select_groups
        chosen, log = select_groups(con, ROOT / "config" / "feature_groups.json")
        for g, ll, ci, ok in log:
            print(f"{'added' if ok else 'stopped at'} {g}: log loss {ll:.4f}, change [{ci[1]:+.4f}, {ci[2]:+.4f}]")
        print("keep:", chosen)
        return 0
    if args.cmd == "event-check":
        from ufcmodel.reports.event_check import replay, replay_last, summarize, summarize_many
        if args.last:
            text = summarize_many(replay_last(con, args.last))
            (ROOT / "docs" / f"replay_last_{args.last}.md").write_text(text, encoding="utf-8")
            print(text)
        else:
            print(summarize(*replay(con, args.event)))
        return 0
    if args.cmd == "styles":
        from ufcmodel.styles.report import build
        print(build(con, ROOT / "docs" / "phase5_styles.md", ROOT / "docs" / "style_labels_template.csv"))
        return 0
    if args.cmd == "skills":
        from ufcmodel.eval import phase4
        from ufcmodel.features.asof import build_features, load_raw
        raw, statics = load_raw(con)
        rows = build_features(raw, statics)
        names = dict(con.execute("SELECT fighter_id, name FROM fighters").fetchall())
        text = phase4.evaluate(rows) + "\n" + phase4.skill_sheet(rows, names)
        (ROOT / "docs" / "phase4_skills.md").write_text(text, encoding="utf-8")
        print(text.split("Finishes")[0])
        return 0
    if args.cmd == "fightweek":
        from ufcmodel.reports.fightweek import build
        print(f"{build(con, args.card, args.out)} bouts written to {args.out}")
        return 0
    if args.cmd == "import-tags":
        from ufcmodel.tagging.import_tags import load_tag_files, takedown_crosscheck
        print(f"{load_tag_files(con, args.directory, args.pass_no)} events loaded")
        for m in takedown_crosscheck(con):
            print("takedown mismatch (bout, fighter, tagged, UFCStats):", m)
        return 0
    if args.cmd == "phase10":
        from ufcmodel.eval.phase10 import run
        print(run(con, ROOT / "docs" / "phase10_evaluation.md", with_ablation=not args.no_ablation))
        return 0
    if args.cmd == "holdout":
        from ufcmodel.eval.phase10 import holdout_report
        out = ROOT / "docs" / "phase10_holdout.md"
        if out.exists() and not args.force:
            print(f"{out.name} already exists: the holdout is scored once. Pass --force only to deliberately re-score.")
            return 1
        print(holdout_report(con, out))
        return 0
    if args.cmd == "load":
        for table, n in load_csv_dir(con, args.directory).items():
            print(f"{table}: {n} rows")
        return 0
    text, hard = report(run_checks(con, cfg["qa"]["round_seconds"],
                                   (cfg["qa"]["overround_min"], cfg["qa"]["overround_max"])))
    print(text)
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
