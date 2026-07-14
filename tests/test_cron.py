# Author: Tom Sapletta · Part of the ifURI solution.
from __future__ import annotations

from urirun_connector_cron import core


def test_bindings_expose_all_surfaces():
    b = core.urirun_bindings()["bindings"]
    for r in ("cron://host/entry/query/list", "cron://host/calendar/query/upcoming",
              "cron://host/entry/command/add", "cron://host/export/query/ics"):
        assert r in b


def test_human_to_cron():
    assert core.human_to_cron("codziennie 08:00") == "0 8 * * *"
    assert core.human_to_cron("co godzine") == "0 * * * *"
    assert core.human_to_cron("30 6 * * 1") == "30 6 * * 1"
    assert core.human_to_cron("bez sensu") is None


def test_cron_match_and_calendar():
    # a daily-08:00 entry matches only at 08:00
    import datetime as dt
    assert core._matches(["0", "8", "*", "*", "*"], dt.datetime(2026, 7, 6, 8, 0))
    assert not core._matches(["0", "8", "*", "*", "*"], dt.datetime(2026, 7, 6, 8, 1))


def test_ics_export_from_synthetic_entries(monkeypatch):
    monkeypatch.setattr(core, "_entries", lambda: [
        {"schedule": "0 8 * * *", "fields": ["0", "8", "*", "*", "*"],
         "command": "echo hi", "id": "u1", "label": "codzienny przegląd", "managed": True}])
    r = core.export_query_ics(mode="rrule")
    assert r["ok"] and "BEGIN:VCALENDAR" in r["ics"] and "RRULE:FREQ=DAILY" in r["ics"]
    assert "codzienny przegląd" in r["ics"] and r["events"] == 1
    ev = core.export_query_ics(mode="events")
    assert ev["events"] >= 1 and "RRULE" not in ev["ics"]


def test_google_csv(monkeypatch):
    monkeypatch.setattr(core, "_entries", lambda: [
        {"schedule": "0 8 * * *", "fields": ["0", "8", "*", "*", "*"],
         "command": "echo hi", "id": "u1", "label": "przegląd", "managed": True}])
    r = core.export_query_google_csv(days=3)
    assert r["ok"] and r["csv"].startswith("Subject,Start Date")
