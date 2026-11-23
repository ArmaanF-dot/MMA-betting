"""Short-notice flag from the fighter pages.

A fighter Y whose page lists two matchups on the same event date, Y vs X (which happened) and Y vs Z (which did not), had a
partner pull out: X is the replacement if the X-Y matchup was created later (its matchup id is higher). Only Y's own page shows the
cancelled matchup, so X's status is known only when Y's page has been read; the table says which statuses are known, and
everything else is left unknown rather than assumed to be no.
Written to `short_notice` in data/processed/odds_oc.duckdb."""
import gzip
from collections import defaultdict
from datetime import timedelta

import duckdb

from ufcmodel.ingest.bfo import _lookup, norm
from ufcmodel.ingest.bfo_fighters import RAW, parse_fighter
from ufcmodel.ingest.bfo_load import OUT


def build(main_path="data/processed/ufc.duckdb", out_path=OUT):
    con = duckdb.connect(main_path, read_only=True)
    alias = _lookup(con)
    bouts = con.execute("""SELECT b.bout_id, r.fighter_id, u.fighter_id, e.date FROM bouts b JOIN events e USING (event_id)
        JOIN bout_fighter r ON r.bout_id = b.bout_id AND r.corner = 'red' JOIN bout_fighter u ON u.bout_id = b.bout_id AND u.corner = 'blue'""").fetchall()
    con.close()
    rows = defaultdict(list)       # (fighter_id, date) -> [(opponent_id, mu)], from the fighter's own page
    owned = set()
    for f in sorted(RAW.glob("*.html.gz")):
        for r in parse_fighter(gzip.decompress(f.read_bytes()).decode("utf-8")):
            fa, fb = alias.get(norm(r["fighter"] or "")), alias.get(norm(r["opponent"] or ""))
            if fa:
                owned.add(fa)
            if fa and fb and r["date"]:
                rows[(fa, r["date"])].append((fb, r["mu"]))

    def other_matchups(y, x, d):
        """Matchups of y on date d (within a day) against someone other than x: [(opponent, mu)]; plus the mu of the y-x matchup."""
        out, mu_x = [], None
        for k in (-1, 0, 1):
            for opp, mu in rows.get((y, d + timedelta(days=k)), []):
                if opp == x:
                    mu_x = mu_x or mu
                else:
                    out.append((opp, mu))
        return out, mu_x

    def replacement(x, y, d):
        """(is_replacement, known): is x the late replacement against y?"""
        if y not in owned:
            return False, False
        others, mu_x = other_matchups(y, x, d)
        late = [mu for _, mu in others if mu is not None and mu_x is not None and mu_x > mu]
        return bool(late), True
    out = duckdb.connect(out_path)
    out.execute("""CREATE OR REPLACE TABLE short_notice (bout_id VARCHAR, red_replacement BOOLEAN, red_known BOOLEAN,
                   blue_replacement BOOLEAN, blue_known BOOLEAN)""")
    data = []
    for b, r, u, d in bouts:
        rr, rk = replacement(r, u, d)
        br, bk = replacement(u, r, d)
        data.append((b, rr, rk, br, bk))
    out.executemany("INSERT INTO short_notice VALUES (?,?,?,?,?)", data)
    n = out.execute("SELECT count(*), sum(CAST(red_known AND blue_known AS INT)), sum(CAST(red_replacement OR blue_replacement AS INT)) FROM short_notice").fetchone()
    out.close()
    return dict(bouts=n[0], both_known=n[1], flagged=n[2], pages_owned=len(owned))


if __name__ == "__main__":
    print(build())
