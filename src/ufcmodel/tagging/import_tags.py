"""Load tagger.html exports into the `tags` table, and check them (Cohen's kappa, takedown cross-check)."""
import json
from collections import Counter, defaultdict
from pathlib import Path

KAPPA_MIN = 0.6


def load_tag_files(con, directory: str | Path, pass_no: int = 1) -> int:
    """Each `<bout_id>.json` holds {bout_id, tagger, events: [{round, t, type, fighter, ...}]}. Replaces that bout's rows for the pass."""
    n = 0
    for f in sorted(Path(directory).glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        con.execute("DELETE FROM tags WHERE bout_id = ? AND pass_no = ?", [doc["bout_id"], pass_no])
        for e in doc["events"]:
            extra = {k: v for k, v in e.items() if k not in ("round", "t", "type", "fighter")}
            con.execute("INSERT INTO tags VALUES (?,?,?,?,?,?,?,?)",
                        [doc["bout_id"], doc.get("tagger", ""), pass_no, e["round"], e["t"], e["type"],
                         e.get("fighter"), json.dumps(extra, sort_keys=True)])
            n += 1
    return n


def cohens_kappa(a: list, b: list) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("need two equal-length, non-empty label lists")
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb.get(k, 0) for k in ca) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def field_kappas(con, bout_ids: list[str]) -> dict[str, tuple[float, int, bool]]:
    """Compare pass 1 with pass 2 per field. Events are paired by (bout, round, type) and order within that key.
    Returns {field: (kappa, n pairs, ok)}; a field under KAPPA_MIN needs a tighter definition or should be dropped."""
    pairs: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for bid in bout_ids:
        passes = {}
        for p in (1, 2):
            rows = con.execute("SELECT round, event_type, t_sec, fighter, fields FROM tags WHERE bout_id=? AND pass_no=? ORDER BY round, event_type, t_sec", [bid, p]).fetchall()
            keyed = defaultdict(list)
            for r, et, t, fighter, fields in rows:
                keyed[(r, et)].append({"fighter": fighter, **json.loads(fields)})
            passes[p] = keyed
        for key, evs1 in passes[1].items():
            for e1, e2 in zip(evs1, passes[2].get(key, [])):
                for fld in set(e1) | set(e2):
                    pairs[f"{key[1]}.{fld}"].append((str(e1.get(fld)), str(e2.get(fld))))
    out = {}
    for fld, pr in pairs.items():
        if len(pr) >= 5:
            k = cohens_kappa([x for x, _ in pr], [y for _, y in pr])
            out[fld] = (k, len(pr), k >= KAPPA_MIN)
    return out


def takedown_crosscheck(con, bout_ids: list[str] | None = None) -> list[tuple]:
    """Tagged landed takedowns per fighter vs UFCStats totals; returns the mismatches (bout, fighter, tagged, official)."""
    where = "" if not bout_ids else f"AND t.bout_id IN ({','.join('?' * len(bout_ids))})"
    rows = con.execute(f"""
        SELECT t.bout_id, t.fighter, count(*) FROM tags t
        WHERE t.event_type = 'takedown_attempt' AND t.pass_no = 1 AND json_extract_string(t.fields, '$.result') LIKE 'landed%' {where}
        GROUP BY 1, 2""", bout_ids or []).fetchall()
    out = []
    for bid, side, tagged in rows:
        corner = "red" if side == "A" else "blue"
        official = con.execute("""SELECT tt.td_l FROM bout_totals tt JOIN bout_fighter f USING (bout_id, fighter_id)
                                  WHERE tt.bout_id = ? AND f.corner = ?""", [bid, corner]).fetchone()
        if official is None or official[0] is None or official[0] != tagged:
            out.append((bid, side, tagged, None if official is None else official[0]))
    return out
