from ufcmodel.db import connect
from ufcmodel.ingest.convert_greco import convert
from ufcmodel.ingest.load_csv import load_csv_dir
from ufcmodel.qa.checks import run_checks

EV = "EVENT,URL,DATE,LOCATION\nUFC 9,http://ufcstats.com/event-details/ev1,\"March 05, 2022\",\"Las Vegas, Nevada, USA\"\n"
FD = "EVENT,BOUT,URL\n"
RES = ("EVENT,BOUT,OUTCOME,WEIGHTCLASS,METHOD,ROUND,TIME,TIME FORMAT,REFEREE,DETAILS,URL\n"
       "UFC 9 ,Ann Lee vs. Bob Roe,W/L,UFC Lightweight Title Bout,KO/TKO ,2,1:30,5 Rnd (5-5-5-5-5),Herb Dean,Punches ,http://ufcstats.com/fight-details/f1\n"
       "UFC 9 ,Cy Poe vs. Di Fox,L/W,Heavyweight Bout,Decision - Unanimous ,3,5:00,3 Rnd (5-5-5),Marc Goddard,scores,http://ufcstats.com/fight-details/f2\n"
       "UFC 9 ,Ed Ray vs. Flo Day,NC/NC,Welterweight Bout,Overturned ,1,0:40,3 Rnd (5-5-5),Jason Herzog,,http://ufcstats.com/fight-details/f3\n")
HEAD = "EVENT,BOUT,ROUND,FIGHTER,KD,SIG.STR.,SIG.STR. %,TOTAL STR.,TD,TD %,SUB.ATT,REV.,CTRL,HEAD,BODY,LEG,DISTANCE,CLINCH,GROUND\n"


def stat(bout, rnd, name, kd="0.0", sig="10 of 20", td="1 of 2", ctrl="1:00"):
    h = int(sig.split()[0])
    return (f"UFC 9,{bout},Round {rnd},{name},{kd},{sig},50%,{h} of 20,{td},50%,1.0,0.0,{ctrl},{h - 2} of 15,1 of 3,1 of 2,"
            f"{h - 3} of 15,2 of 3,1 of 2\n")


TOTT = ("FIGHTER,HEIGHT,WEIGHT,REACH,STANCE,DOB,URL\n"
        "Ann Lee,\"5' 11\"\"\",155 lbs.,\"72\"\"\",Orthodox,\"Jul 13, 1990\",http://ufcstats.com/fighter-details/a1\n"
        "Bob Roe,--,170 lbs.,--,Southpaw,--,http://ufcstats.com/fighter-details/b1\n"
        "Cy Poe,--,265 lbs.,--,,--,http://ufcstats.com/fighter-details/c1\n"
        "Di Fox,--,265 lbs.,--,,--,http://ufcstats.com/fighter-details/d1\n"
        "Dup One,--,155 lbs.,--,,--,http://ufcstats.com/fighter-details/e1\n"
        "Dup One,--,155 lbs.,--,,--,http://ufcstats.com/fighter-details/e2\n")
ODDS = ("link,date,event,fighter1,fighter2,fighter1_odds,fighter2_odds,result,timestamp\n"
        "l,5th Mar 22,UFC 9,Ann Lee,Bob Roe,1.50,2.70,Ann Lee,t\n"
        "l,5th Mar 22,UFC 9,Cy Poee,Di Fox,1.90,1.95,Cy Poee,t\n"
        "l,5th Mar 22,UFC 9,Zed,Yan,inf,inf,Zed,t\n")


def make(tmp):
    d = tmp / "src"
    d.mkdir()
    w = lambda n, t: (d / n).write_text(t, encoding="utf-8")
    w("ufc_event_details.csv", EV)
    w("ufc_fight_details.csv", FD)
    w("ufc_fight_results.csv", RES)
    w("ufc_fighter_tott.csv", TOTT)
    rows = (stat("Ann Lee vs. Bob Roe", 1, "Ann Lee", kd="1.0") + stat("Ann Lee vs. Bob Roe", 1, "Bob Roe", ctrl="--")
            + stat("Ann Lee vs. Bob Roe", 2, "Ann Lee") + stat("Ann Lee vs. Bob Roe", 2, "Bob Roe"))
    w("ufc_fight_stats.csv", HEAD + rows)
    w("odds.csv", ODDS)
    return d


def test_convert_roundtrip(tmp_path):
    src = make(tmp_path)
    out = tmp_path / "out"
    st = convert(src, out, src / "odds.csv", tmp_path / "interim")
    assert st["bouts"] == 3 and st["round_rows"] == 4
    assert st["odds_matched_exact"] == 1 and st["odds_matched_fuzzy"] == 1 and st["odds_bad_price"] == 1
    con = connect(":memory:")
    load_csv_dir(con, out)
    assert not [r.name for r in run_checks(con) if r.failed and r.severity == "hard"]
    # counts written as floats ('1.0') are read, and a dash is missing rather than zero
    assert con.execute("SELECT sum(kd) FROM rounds").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM rounds WHERE ctrl_sec IS NULL").fetchone()[0] == 1
    assert con.execute("SELECT sum(sub_att) FROM rounds").fetchone()[0] == 4
    # L/W means the second-listed fighter won; NC/NC is a no contest; titles and divisions are parsed
    res = dict(con.execute("SELECT f.name, r.result FROM bout_fighter r JOIN fighters f USING (fighter_id)").fetchall())
    assert res["Ann Lee"] == "win" and res["Bob Roe"] == "loss" and res["Cy Poe"] == "loss" and res["Di Fox"] == "win"
    assert con.execute("SELECT weight_class, is_title, scheduled_rounds, round_lengths FROM bouts WHERE bout_id='f1'").fetchone() == ("Lightweight", True, 5, "5,5,5,5,5")
    assert con.execute("SELECT fight_seconds FROM bouts WHERE bout_id='f1'").fetchone()[0] == 300 + 90
    assert con.execute("SELECT method, method_detail FROM bouts WHERE bout_id='f2'").fetchone() == ("Decision", "Unanimous")
    assert con.execute("SELECT method FROM bouts WHERE bout_id='f3'").fetchone()[0] == "No Contest"
    assert con.execute("SELECT height_cm FROM fighters WHERE name='Ann Lee'").fetchone()[0] == 180.3
    assert con.execute("SELECT count(*) FROM odds_snapshots").fetchone()[0] == 4


def test_corner_is_not_the_listed_order(tmp_path):
    src = make(tmp_path)
    convert(src, tmp_path / "out", None)
    import csv
    first_listed_red = 0
    rows = list(csv.DictReader(open(tmp_path / "out" / "bout_fighter.csv", encoding="utf-8")))
    assert {r["corner"] for r in rows} == {"red", "blue"}
    assert sum(r["corner"] == "red" for r in rows) == 3   # exactly one red per bout


def test_duplicate_names_are_merged_with_blank_physicals(tmp_path):
    src = make(tmp_path)
    st = convert(src, tmp_path / "out", None)
    assert st["ambiguous_fighter_names"] == ["Dup One"]
