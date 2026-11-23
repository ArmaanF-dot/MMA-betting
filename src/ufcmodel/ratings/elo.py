"""B1: Elo on results only. Every bout of an event is predicted before any of that event's results are applied."""
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class Bout:
    bout_id: str
    event_id: str
    date: str          # ISO date, sortable
    order: int         # position within the event, only used for stable ordering
    a: str             # fighter A (red corner)
    b: str
    score_a: float | None  # 1 win, 0 loss, 0.5 draw, None = no contest (skipped)


def expected(ra: float, rb: float) -> float:
    return 1 / (1 + 10 ** ((rb - ra) / 400))


def run_elo(bouts: list[Bout], k: float, base: float = 1500.0) -> dict[str, float]:
    """Return P(A wins) for every bout, using only results from earlier events."""
    ordered = sorted(bouts, key=lambda x: (x.date, x.event_id, x.order))
    ratings: dict[str, float] = defaultdict(lambda: base)
    out: dict[str, float] = {}
    i = 0
    while i < len(ordered):
        j = i
        while j < len(ordered) and ordered[j].event_id == ordered[i].event_id and ordered[j].date == ordered[i].date:
            j += 1
        event = ordered[i:j]
        updates: dict[str, float] = defaultdict(float)
        for x in event:
            e = expected(ratings[x.a], ratings[x.b])
            out[x.bout_id] = e
            if x.score_a is not None:
                updates[x.a] += k * (x.score_a - e)
                updates[x.b] += k * ((1 - x.score_a) - (1 - e))
        for f, d in updates.items():
            ratings[f] += d
        i = j
    return out
