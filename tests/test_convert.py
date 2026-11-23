import csv

from ufcmodel.db import connect
from ufcmodel.ingest.convert_ufc_data import convert, slug
from ufcmodel.ingest.load_csv import load_csv_dir
from ufcmodel.qa.checks import run_checks

EV_HEAD = "event_name,event_date,event_location,Weight class,fighter1,fighter2,outcome,Kd,Str,Td,Sub,Method,Round,Time,timestamp\n"
FI_HEAD = "name,fight_record,nickname,Height,Weight,Reach,STANCE,DOB,SLpM,Str.Acc.,SApM,Str.Def,TDAvg.,TDAcc.,TDDef.,Sub.Avg.,timestamp\n"
OD_HEAD = "link,date,event,fighter1,fighter2,fighter1_odds,fighter2_odds,result,timestamp\n"


def _w(path, text):
    path.write_text(text, encoding="utf-8")


def make_src(tmp_path):
    _w(tmp_path / "events_raw.csv", 
        EV_HEAD
        + 'UFC 1,March 05 2022,"Las Vegas, Nevada, USA",Lightweight,José Aldo,Max Holloway,fighter1,1   0,10   4,0   0,0   0,KO/TKO   Punches,2,1:30,t\n'
        + 'UFC 1,March 05 2022,"Las Vegas, Nevada, USA",Welterweight,Annabelle Leighton,Bob Roe,Draw,--,--,--,--,S-DEC,3,5:00,t\n'
        + 'UFC 1,March 05 2022,"Las Vegas, Nevada, USA",Welterweight,Cy Poe,Di Fox,No contest,0   0,5   5,0   0,0   0,CNC,1,2:00,t\n'
    )
    _w(tmp_path / "fighters_raw.csv", 
        FI_HEAD
        + 'José Aldo,31-8-0,,"5\'7""",145lbs.,70",Orthodox,"Sep09,1986",1,1,1,1,1,1,1,1,t\n'
        + "Max Holloway,25-7-0,,--,145lbs.,--,,--,1,1,1,1,1,1,1,1,t\n"
    )
    _w(tmp_path / "odds_raw.csv", 
        OD_HEAD
        + "l,5th Mar 22,UFC 1,Jose Aldo,Max Holloway,1.50,2.70,Jose Aldo,t\n"       # exact after accent strip
        + "l,5th Mar 22,UFC 1,Annabelle Leighten,Bob Roe,1.90,1.95,Annabelle Leighten,t\n"               # fuzzy name
        + "l,5th Mar 22,UFC 1,Cy Poe,Di Fox,inf,inf,Cy Poe,t\n"                    # missing odds
        + "l,9th Dec 25,UFC 9,Nobody,Else,1.5,2.5,Nobody,t\n"                      # no such bout
    )
    return tmp_path


def test_slug_strips_accents():
    assert slug("José Aldo") == slug("Jose Aldo") == "jose-aldo"


def test_convert_roundtrip_passes_qa(tmp_path):
    (tmp_path / "src").mkdir()
    src = make_src(tmp_path / "src")
    out = tmp_path / "out"
    stats = convert(src, out, tmp_path / "interim")
    assert stats["bouts"] == 3 and stats["events"] == 1
    assert stats["odds_matched_exact"] == 1 and stats["odds_matched_fuzzy"] == 1
    assert stats["odds_bad_price"] == 1 and stats["odds_unmatched"] == 1
    con = connect(":memory:")
    load_csv_dir(con, out)
    assert not [r.name for r in run_checks(con) if r.failed and r.severity == "hard"]

    results = dict(con.execute("SELECT fighter_id, result FROM bout_fighter").fetchall())
    assert results["jose-aldo"] == "win" and results["max-holloway"] == "loss"
    assert results["annabelle-leighton"] == "draw" and results["cy-poe"] == "nc"
    # unknown stats stay NULL rather than becoming zero
    assert con.execute("SELECT sig_l FROM bout_totals WHERE fighter_id = 'annabelle-leighton'").fetchone()[0] is None
    assert con.execute("SELECT height_cm FROM fighters WHERE fighter_id = 'jose-aldo'").fetchone()[0] == 170.2


def test_corner_does_not_follow_listed_winner_order(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    rows = "".join(
        f'UFC {i},{'January' if i < 20 else 'February'} {i % 20 + 1:02d} 2020,"X, Y, Z",Lightweight,W{i},L{i},fighter1,0   0,1   1,0   0,0   0,U-DEC,3,5:00,t\n'
        for i in range(40)
    )
    _w(src / "events_raw.csv", EV_HEAD + rows)
    _w(src / "fighters_raw.csv", FI_HEAD)
    _w(src / "odds_raw.csv", OD_HEAD)
    out = tmp_path / "out"
    convert(src, out)
    with open(out / "bout_fighter.csv", encoding="utf-8") as f:
        reds = [r for r in csv.DictReader(f) if r["corner"] == "red"]
    winners_red = sum(r["result"] == "win" for r in reds)
    assert 10 < winners_red < 30  # roughly half, not all
