"""One place for the betting arithmetic that earlier ad-hoc scripts repeated: margin removal, the market of record, flat-stake
returns with event-clustered intervals, closing-line value, and model-vs-market log loss.

Market of record (fair probability that the red corner wins), best source first:
  close: median over sportsbooks of each book's margin-free price pair (3+ books, 2023-06 on), else the midpoint of the closing
         range on the fighter pages, else the old single-pair file (a stand-in with almost no margin).
  open : the opening pair on the fighter pages.
Margin removal is proportional (each side's implied probability divided by the pair's sum).
"""
import math
from collections import defaultdict
from statistics import median

import duckdb
import numpy as np

from ufcmodel.eval import metrics as M

EXCHANGES = {"Polymarket", "Kalshi"}   # prediction markets: thin, different margin, not open to UK bettors


def devig(price_a: float, price_b: float) -> float:
    """Margin-free probability of side A from the two decimal prices of a two-way market."""
    ia, ib = 1 / price_a, 1 / price_b
    return ia / (ia + ib)


def clv(price_taken: float, fair_close_p: float) -> float:
    """ln(price taken x fair closing probability of that side): above zero means the price taken beat the fair close."""
    return math.log(price_taken * fair_close_p)


def flat_returns(profits, events, stake=10.0, n_boot=4000, seed=0):
    """Return on stake with a 95% interval from a bootstrap over events (fights on one card are not independent).
    `profits` are per-bet profits for a flat `stake`, `events` the event of each bet."""
    profits = np.asarray(profits, float)
    if len(profits) == 0:
        return dict(n=0, profit=0.0, roi=None, lo=None, hi=None)
    by = defaultdict(list)
    for p, e in zip(profits, events):
        by[e].append(p)
    groups = [np.array(v) for v in by.values()]
    rng = np.random.default_rng(seed)
    sums = np.array([g.sum() for g in groups])
    cnts = np.array([len(g) for g in groups])
    idx = rng.integers(0, len(groups), (n_boot, len(groups)))
    roi = sums[idx].sum(axis=1) / cnts[idx].sum(axis=1) / stake
    return dict(n=len(profits), profit=float(profits.sum()), roi=float(profits.mean() / stake),
                lo=float(np.percentile(roi, 2.5)), hi=float(np.percentile(roi, 97.5)))


def flat_profit(price: float, won: bool, stake=10.0) -> float:
    return stake * (price - 1) if won else -stake


def loss_gap(model_p, market_p, y):
    """Mean log loss of each, and the paired bootstrap of model minus market (positive = model worse): (mean, lo, hi)."""
    lm, lk = M.per_bout_log_loss(np.asarray(model_p), np.asarray(y)), M.per_bout_log_loss(np.asarray(market_p), np.asarray(y))
    return dict(model=float(lm.mean()), market=float(lk.mean()), gap=M.paired_bootstrap_diff(lm, lk))


class MarketOfRecord:
    """Fair probabilities by bout from the three sources, read-only. `oc_path` may be missing (no fighter-page data yet)."""

    def __init__(self, main_path="data/processed/ufc.duckdb", oc_path="data/processed/odds_oc.duckdb"):
        con = duckdb.connect(main_path, read_only=True)
        self.red = dict(con.execute("SELECT bout_id, fighter_id FROM bout_fighter WHERE corner = 'red'").fetchall())
        self.blue = dict(con.execute("SELECT bout_id, fighter_id FROM bout_fighter WHERE corner = 'blue'").fetchall())
        books = defaultdict(lambda: defaultdict(dict))
        try:
            for b, bk, f, p in con.execute("SELECT bout_id, bookmaker, fighter_id, price_decimal FROM odds_books").fetchall():
                if bk not in EXCHANGES:
                    books[b][bk][f] = p
        except duckdb.CatalogException:
            pass
        self.books = books
        self.old = defaultdict(dict)
        for b, f, p in con.execute("SELECT bout_id, fighter_id, price_decimal FROM odds_snapshots").fetchall():
            self.old[b][f] = p
        con.close()
        self.oc = {}
        try:
            oc = duckdb.connect(oc_path, read_only=True)
            cols = [c[0] for c in oc.execute("DESCRIBE odds_open_close").fetchall()]
            self.oc = {r[0]: dict(zip(cols, r)) for r in oc.execute("SELECT * FROM odds_open_close").fetchall()}
            oc.close()
        except duckdb.IOException:
            pass

    def book_prices(self, bout):
        """[(price_red, price_blue)] per sportsbook with a usable pair (implied sum between 1.00 and 1.15)."""
        r, u = self.red.get(bout), self.blue.get(bout)
        out = []
        for d in self.books.get(bout, {}).values():
            if r in d and u in d and 1 < d[r] < 50 and 1 < d[u] < 50 and 1.0 <= 1 / d[r] + 1 / d[u] <= 1.15:
                out.append((d[r], d[u]))
        return out

    def close(self, bout):
        """(fair p_red, source) or (None, None)."""
        pr = self.book_prices(bout)
        if len(pr) >= 3:
            return float(median(devig(a, b) for a, b in pr)), "books"
        o = self.oc.get(bout)
        if o and all(o[k] for k in ("low_red", "high_red", "low_blue", "high_blue")):
            return devig((o["low_red"] + o["high_red"]) / 2, (o["low_blue"] + o["high_blue"]) / 2), "range"
        old = self.old.get(bout, {})
        r, u = self.red.get(bout), self.blue.get(bout)
        if r in old and u in old:
            return devig(old[r], old[u]), "old"
        return None, None

    def open(self, bout):
        o = self.oc.get(bout)
        return devig(o["open_red"], o["open_blue"]) if o and o["open_red"] and o["open_blue"] else None

    def best(self, bout):
        """Best price on each side across sportsbooks, (red, blue), or None."""
        pr = self.book_prices(bout)
        return (max(a for a, _ in pr), max(b for _, b in pr)) if pr else None
