from datetime import date, datetime

from ufcmodel.reports import capture as C


def test_slot_times_for_a_sunday_event_date():
    # Vegas 123 is listed as Sunday 2026-11-01 (a US Saturday card): fight week is Mon 26 Oct to Sat 31 Oct
    t = C.slot_times(date(2026, 11, 1))
    assert t["mon"] == datetime(2026, 10, 26, 12, 0)
    assert t["thu"] == datetime(2026, 10, 29, 12, 0)
    assert t["pre"] == datetime(2026, 10, 31, 20, 0)


def test_slot_times_for_a_saturday_event_date():
    t = C.slot_times(date(2026, 11, 14))
    assert t["mon"] == datetime(2026, 11, 9, 12, 0) and t["thu"] == datetime(2026, 11, 12, 12, 0) and t["pre"] == datetime(2026, 11, 14, 15, 0)


def test_due_and_missed_slots():
    d = date(2026, 11, 1)
    run, missed = C.due_slots(datetime(2026, 10, 27, 18, 0), d, {})
    assert run == [] and missed == ["mon"]                           # Monday's window has passed; nothing else is due yet
    run, missed = C.due_slots(datetime(2026, 10, 29, 12, 30), d, {"mon": "missed"})
    assert run == ["thu"] and missed == []
    run, missed = C.due_slots(datetime(2026, 10, 29, 12, 30), d, {"mon": "missed", "thu": "done"})
    assert run == [] and missed == []                                # already settled, not run twice
    run, _ = C.due_slots(datetime(2026, 10, 31, 21, 0), d, {"mon": "missed", "thu": "done"})
    assert run == ["pre"]
    _, missed = C.due_slots(datetime(2026, 10, 31, 23, 30), d, {"mon": "done", "thu": "done"})
    assert missed == ["pre"]                                         # the 3 hour window is over


def test_parse_front_page_links():
    html = """<a href="/events/aca-209-4431">View ACA 209 Odds (October 30th) -></a>
              <a href="/events/ufc-vegas-123-4427">View UFC Vegas 123 Odds (November 1st) -></a>
              <a href="/events/ufc-vegas-123-4427">UFC Vegas 123 Odds</a>
              <a href="/events/ufc-334-4433">View UFC 334 Odds (November 14th) -></a>"""
    got = C.parse_upcoming(html, date(2026, 10, 27))
    assert [(e["slug"], e["date"]) for e in got] == [("ufc-vegas-123-4427", "2026-11-01"), ("ufc-334-4433", "2026-11-14")]
    assert C.parse_upcoming('<a href="/events/ufc-1-1">View UFC 1 Odds (January 3rd) -></a>', date(2026, 12, 20))[0]["date"] == "2027-01-03"


def test_tick_runs_listed_once_and_marks_missed(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "STATE", tmp_path / "s.json")
    monkeypatch.setattr(C, "LOG", tmp_path / "l.log")
    calls = []
    monkeypatch.setattr(C, "run_capture", lambda url, d, slot: (calls.append(slot) or True, "ok"))
    monkeypatch.setattr(C, "discover", lambda st, now: st["events"].setdefault("ev", dict(url="u", date="2026-11-01", slots={"listed": "pending"})) and st.update(last_discovery=now.isoformat()))
    C.tick(datetime(2026, 10, 27, 18, 0))
    assert calls == ["listed"]
    st = C.load_state()
    assert st["events"]["ev"]["slots"]["mon"] == "missed" and st["events"]["ev"]["slots"]["listed"].startswith("done")
    C.tick(datetime(2026, 10, 27, 18, 15))
    assert calls == ["listed"]                                       # nothing new to do 15 minutes later
    C.tick(datetime(2026, 10, 29, 12, 20))
    assert calls == ["listed", "thu"]


def test_failed_capture_is_retried_then_given_up(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "STATE", tmp_path / "s.json")
    monkeypatch.setattr(C, "LOG", tmp_path / "l.log")
    monkeypatch.setattr(C, "run_capture", lambda url, d, slot: (False, "database is locked"))
    C.save_state({"last_discovery": datetime(2026, 10, 29, 11, 0).isoformat(), "events": {"ev": dict(url="u", date="2026-11-01", slots={"listed": "done", "mon": "missed"})}})
    for k in range(8):
        C.tick(datetime(2026, 10, 29, 12, 5 + k), skip_discovery=True)
    assert C.load_state()["events"]["ev"]["slots"]["thu"] == "gave up"
