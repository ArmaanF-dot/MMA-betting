import pytest

from ufcmodel.db import connect
from ufcmodel.ingest.fetch import BlockedError, Fetcher, looks_like_challenge
from ufcmodel.ingest.load_csv import load_csv_dir

CHALLENGE = "<html><title>Loading…</title><p>Checking your browser…</p></html>"


def test_challenge_detection():
    assert looks_like_challenge(CHALLENGE)
    assert not looks_like_challenge("<html><table><tr><td>UFC 300</td></tr></table></html>")


def test_fetcher_refuses_challenge_and_does_not_cache(tmp_path, monkeypatch):
    f = Fetcher(tmp_path, "test-agent", min_delay_sec=0)
    monkeypatch.setattr(f, "_allowed", lambda url: True)

    class R:
        status_code, text = 200, CHALLENGE
        def raise_for_status(self): pass

    monkeypatch.setattr(f.client, "get", lambda url: R())
    with pytest.raises(BlockedError):
        f.get("http://example.test/x")
    assert not list(tmp_path.glob("*.html"))


def test_load_csv_roundtrip_and_idempotent(tmp_path):
    (tmp_path / "events.csv").write_text("event_id,name,date\ne1,UFC 1,1993-11-12\n")
    con = connect(":memory:")
    assert load_csv_dir(con, tmp_path) == {"events": 1}
    assert load_csv_dir(con, tmp_path) == {"events": 1}


def test_load_csv_rejects_unknown_columns(tmp_path):
    (tmp_path / "events.csv").write_text("event_id,bogus\ne1,x\n")
    with pytest.raises(ValueError):
        load_csv_dir(connect(":memory:"), tmp_path)
