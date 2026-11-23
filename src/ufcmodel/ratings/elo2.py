"""Improved Elo ("Elo2"): margin of victory plus a Glicko-style rating deviation.

- Margin of victory: a finish or a lopsided striking fight moves ratings more than a close decision.
- Rating deviation (RD): starts high for a newcomer, shrinks with every fight, grows again with time out. A high-RD fighter's
  rating moves more, and a matchup involving high-RD fighters is pulled towards 50% (the Glicko g-factor). An unbeaten run
  against middling opponents therefore earns a confident rating only slowly.
Parameters were tuned on bouts before 2015 only (`tune`), so the walk-forward test years never informed them.
"""
import math
from collections import defaultdict
from itertools import product

Q = math.log(10) / 400
RD0, RD_MIN = 200.0, 60.0
# tuned by `tune` on 2005-2014 bouts (log loss 0.6749 vs 0.6753 for no margin and no layoff term: a small gain)
PARAMS = dict(k0=48.0, mov=1.0, layoff=40.0, shrink=0.9)


def g(rd2):
    return 1 / math.sqrt(1 + 3 * Q * Q * rd2 / math.pi ** 2)


def rd_now(rd, last, d, layoff):
    if last is None:
        return RD0
    years = (d - last).days / 365.25
    return min(RD0, math.sqrt(rd * rd + layoff * layoff * years))


def expected(ra, rb, rda, rdb):
    return 1 / (1 + 10 ** (-g(rda * rda + rdb * rdb) * (ra - rb) / 400))


def margin(score_a, cat, sig_a, sig_b, mov):
    if score_a == 0.5:
        return 1.0
    finish = 1.0 if cat in ("KO", "SUB") else 0.0
    dom = abs(sig_a - sig_b) / (sig_a + sig_b + 10.0) if sig_a is not None and sig_b is not None else 0.0
    return 1.0 + mov * (0.5 * finish + 0.5 * dom)


class Elo2:
    def __init__(self, k0, mov, layoff, shrink):
        self.k0, self.mov, self.layoff, self.shrink = k0, mov, layoff, shrink
        self.r = defaultdict(lambda: 1500.0)
        self.rd = defaultdict(lambda: RD0)
        self.last = {}

    def state(self, fid, d):
        return self.r[fid], rd_now(self.rd[fid], self.last.get(fid), d, self.layoff)

    def update_event(self, results, d):
        """results: [(a, b, score_a, cat, sig_a, sig_b)] for one event; all expectations use pre-event ratings."""
        delta, new_rd = defaultdict(float), {}
        for a, b, s, cat, sa, sb in results:
            ra, rda = self.state(a, d)
            rb, rdb = self.state(b, d)
            e = expected(ra, rb, rda, rdb)
            m = margin(s, cat, sa, sb, self.mov)
            delta[a] += self.k0 * (rda / 100) * m * (s - e)
            delta[b] += self.k0 * (rdb / 100) * m * ((1 - s) - (1 - e))
            new_rd[a] = max(RD_MIN, rda * self.shrink)
            new_rd[b] = max(RD_MIN, rdb * self.shrink)
        for f, v in delta.items():
            self.r[f] += v
        for f, v in new_rd.items():
            self.rd[f] = v
            self.last[f] = d


def tune(raw, before="2015-01-01", score_from="2005-01-01"):
    """Grid search on pre-2015 bouts: log loss of Elo2's pre-fight probabilities on 2005-2014 decisive bouts."""
    from datetime import date
    ordered = sorted([b for b in raw if b.date < before], key=lambda x: (x.date, x.event_id, x.order))
    best, out = None, []
    for k0, mov, layoff, shrink in product((24, 32, 48, 64), (0.0, 0.5, 1.0), (0.0, 40.0, 80.0), (0.8, 0.9)):
        el = Elo2(k0, mov, layoff, shrink)
        ll = n = 0
        i = 0
        while i < len(ordered):
            j = i
            while j < len(ordered) and (ordered[j].date, ordered[j].event_id) == (ordered[i].date, ordered[i].event_id):
                j += 1
            d = date.fromisoformat(ordered[i].date)
            res = []
            for b in ordered[i:j]:
                if b.score_a is None:
                    continue
                if b.date >= score_from and b.score_a in (0.0, 1.0):
                    (ra, rda), (rb, rdb) = el.state(b.a, d), el.state(b.b, d)
                    p = min(max(expected(ra, rb, rda, rdb), 1e-6), 1 - 1e-6)
                    ll -= math.log(p if b.score_a == 1.0 else 1 - p)
                    n += 1
                cat = {"KO/TKO": "KO", "Submission": "SUB"}.get(b.method, "DEC")
                res.append((b.a, b.b, b.score_a, cat, b.stats_a.get("sig_l"), b.stats_b.get("sig_l")))
            el.update_event(res, d)
            i = j
        out.append((ll / n, dict(k0=k0, mov=mov, layoff=layoff, shrink=shrink)))
    out.sort(key=lambda t: t[0])
    return out
