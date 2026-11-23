"""Load one CSV per table (header names = column names) into the database.

This is the source-agnostic entry point: any permitted source (a downloaded dataset,
manual entry, or a future scraper) just has to write these CSVs. Tables without a CSV
are left untouched. Loading replaces the table contents, so it is idempotent.
"""
from pathlib import Path

from ufcmodel.db import TABLES


def load_csv_dir(con, directory: str | Path) -> dict[str, int]:
    directory = Path(directory)
    loaded: dict[str, int] = {}
    for table in TABLES:
        f = directory / f"{table}.csv"
        if not f.exists():
            continue
        types = {r[0]: r[1] for r in con.execute(f"DESCRIBE {table}").fetchall()}
        # read everything as text and cast to the table's own types: letting DuckDB sniff types turned the 0s in
        # small-integer columns (kd, sub_att) into NULLs
        src = f"read_csv('{f.as_posix()}', header=true, all_varchar=true)"
        header = [d[0] for d in con.execute(f"SELECT * FROM {src} LIMIT 0").description]
        unknown = [c for c in header if c not in types]
        if unknown:
            raise ValueError(f"{f.name}: unknown columns {unknown}")
        names = ", ".join(header)
        exprs = ", ".join(f"CAST(NULLIF(TRIM({c}), '') AS {types[c]})" for c in header)
        con.execute(f"DELETE FROM {table}")
        con.execute(f"INSERT INTO {table} ({names}) SELECT {exprs} FROM {src}")
        loaded[table] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    return loaded
