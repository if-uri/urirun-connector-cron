from __future__ import annotations
from urirun_connector_cron import core

GOOGLE = "\r\n".join([
 "BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//Google Inc//Google Calendar//EN",
 "BEGIN:VEVENT","DTSTART;TZID=Europe/Warsaw:20260701T080000","RRULE:FREQ=DAILY",
 "SUMMARY:Backup","DESCRIPTION:/opt/backup.sh","END:VEVENT",
 "BEGIN:VEVENT","DTSTART:20260701T173000","RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR",
 "SUMMARY:Raport","DESCRIP","TION:/usr/bin/report",  # zawinięta linia
 "END:VEVENT","END:VCALENDAR"])
# ^ celowo rozbita DESCRIPTION w dwóch elementach symuluje folding? nie — zrób prawdziwy folding:
GOOGLE = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
 "BEGIN:VEVENT\r\nDTSTART;TZID=Europe/Warsaw:20260701T080000\r\nRRULE:FREQ=DAILY\r\n"
 "SUMMARY:Backup\r\nDESCRIPTION:/opt/backup.sh\r\nEND:VEVENT\r\n"
 "BEGIN:VEVENT\r\nDTSTART:20260701T173000\r\nRRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR\r\n"
 "SUMMARY:Raport\r\nDESCRIPTION:/usr/bin/re\r\n port.sh\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")

APPLE = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Apple Inc.//macOS//EN\r\n"
 "BEGIN:VEVENT\r\nDTSTART:20260701T000000\r\nRRULE:FREQ=HOURLY;INTERVAL=2\r\n"
 "SUMMARY:Health check\r\nDESCRIPTION:/usr/local/bin/health\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")

def test_unfold():
    lines=core._unfold_ics("DESCRIPTION:/usr/bin/re\r\n port.sh")
    assert lines==["DESCRIPTION:/usr/bin/report.sh"]

def test_google_daily_and_weekly():
    ents=core._ics_to_entries(GOOGLE)
    by={e["command"]:e["schedule"] for e in ents}
    assert by["/opt/backup.sh"]=="0 8 * * *"           # DAILY @ 08:00
    assert by["/usr/bin/report.sh"]=="30 17 * * 1,3,5"  # WEEKLY MO,WE,FR @ 17:30 (folded command)

def test_apple_hourly_interval():
    ents=core._ics_to_entries(APPLE)
    assert ents[0]["schedule"]=="0 */2 * * *"          # HOURLY;INTERVAL=2

def test_rrule_to_cron_oneshot():
    assert core._rrule_to_cron("","20260704T091500")=="15 9 4 7 *"  # jednorazowe

def test_import_dry_run_no_write():
    r=core.import_command_ics(ics=GOOGLE, add=False)
    assert r["ok"] and r["dry_run"] and r["count"]==2

def test_binding_present():
    b=core.urirun_bindings()["bindings"]
    assert any("import/command/ics" in k for k in b)

def test_caldav_handler_exists_and_delegates(monkeypatch):
    monkeypatch.setattr(core, "_fetch_ics", lambda u: APPLE)
    r=core.import_command_caldav(url="webcal://x/cal.ics", add=False)
    assert r["ok"] and r["action"]=="cron-import-caldav" and r["count"]==1
    assert any("import/command/caldav" in k for k in core.urirun_bindings()["bindings"])
