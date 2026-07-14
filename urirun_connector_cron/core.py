# Author: Tom Sapletta · Part of the ifURI solution.
"""urirun-connector-cron — the machine's schedule as a URI process.

Manage the operator's cron entries (list / add / edit / remove — only lines tagged
``# urirun:<id>`` are touched, the rest of the crontab is preserved), see a **calendar** of
upcoming runs, and **export** those schedules to calendar files that any platform imports:
iCalendar (``.ics`` — Google/Apple/Outlook) and Google-CSV. A schedule is data; this makes it
portable. Built to URI_NATIVE_CONNECTOR_CHECKLIST: lazy imports, handlers never raise, reads
in-process; only add/edit/remove/import mutate (isolated).
"""
from __future__ import annotations

import datetime as _dt
import re
import subprocess
from typing import Any

import urirun

CONNECTOR_ID = "cron"
conn = urirun.connector(CONNECTOR_ID, scheme="cron")

_MARK = re.compile(r"#\s*urirun:(\S+)\s*(.*)$")
_HHMM = re.compile(r"(\d{1,2}):(\d{2})")


def _ok(**kw: Any) -> dict[str, Any]:
    return urirun.ok(connector=CONNECTOR_ID, **kw)


def _fail(msg: str, action: str, **extra: Any) -> dict[str, Any]:
    return urirun.fail(msg, connector=CONNECTOR_ID, action=action, **extra)


# --------------------------------------------------------------- crontab I/O

def _read() -> list[str]:
    try:
        cp = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001
        return []
    return cp.stdout.splitlines() if cp.returncode == 0 else []


def _write(lines: list[str]) -> tuple[bool, str]:
    text = "\n".join(l for l in lines if l is not None).rstrip("\n") + "\n"
    try:
        cp = subprocess.run(["crontab", "-"], input=text, capture_output=True, text=True, timeout=10)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    return cp.returncode == 0, (cp.stderr or "").strip()


def _parse(line: str) -> dict | None:
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    parts = s.split(None, 5)
    if len(parts) < 6:
        return None
    fields, rest = parts[:5], parts[5]
    mm = _MARK.search(rest)
    cid = mm.group(1) if mm else None
    return {"schedule": " ".join(fields), "fields": fields,
            "command": (_MARK.sub("", rest).strip() if mm else rest),
            "id": cid, "label": (mm.group(2).strip() if mm else ""), "managed": bool(cid)}


def _entries() -> list[dict]:
    return [e for e in (_parse(l) for l in _read()) if e]


# --------------------------------------------------------------- human → cron

def human_to_cron(text: str) -> str | None:
    t = (text or "").strip().lower()
    if len(t.split()) == 5 and all(c in "0123456789*/,-" for c in t.replace(" ", "")):
        return t
    hm = _HHMM.search(t)
    hh, mn = (hm.group(1), hm.group(2)) if hm else ("8", "00")
    if any(w in t for w in ("codziennie", "daily", "co dzień", "kazdego dnia")):
        return f"{int(mn)} {int(hh)} * * *"
    if "co godzin" in t or "hourly" in t:
        return "0 * * * *"
    if "co tydzie" in t or "weekly" in t:
        return f"{int(mn)} {int(hh)} * * 1"
    return f"{int(mn)} {int(hh)} * * *" if hm else None


def _gen_id(taken: set[str]) -> str:
    i = 1
    while f"u{i}" in taken:
        i += 1
    return f"u{i}"


# --------------------------------------------------------------- cron matching + calendar

def _field_match(spec: str, value: int) -> bool:
    for part in spec.split(","):
        if part == "*":
            return True
        if part.startswith("*/") and part[2:].isdigit():
            if value % int(part[2:]) == 0:
                return True
        elif "-" in part:
            a, _, b = part.partition("-")
            if a.isdigit() and b.isdigit() and int(a) <= value <= int(b):
                return True
        elif part.isdigit() and int(part) == value:
            return True
    return False


def _matches(fields: list[str], dt: _dt.datetime) -> bool:
    mn, hr, dom, mon, dow = fields
    cd = (dt.weekday() + 1) % 7
    return (_field_match(mn, dt.minute) and _field_match(hr, dt.hour) and _field_match(dom, dt.day)
            and _field_match(mon, dt.month)
            and (_field_match(dow, cd) or _field_match(dow, 7 if cd == 0 else cd)))


def _occurrences(entry: dict, days: int, cap: int) -> list[_dt.datetime]:
    now = _dt.datetime.now().replace(second=0, microsecond=0)
    end = now + _dt.timedelta(days=days)
    out, t = [], now
    while t <= end and len(out) < cap:
        if _matches(entry["fields"], t):
            out.append(t)
        t += _dt.timedelta(minutes=1)
    return out


def _calendar(days: int) -> dict:
    days = max(1, min(int(days), 31))
    ents = [e for e in _entries() if len(e.get("fields") or []) == 5]
    occ = []
    for e in ents:
        for t in _occurrences(e, days, 60):
            occ.append({"when": t.isoformat(timespec="minutes"), "date": t.strftime("%Y-%m-%d"),
                        "time": t.strftime("%H:%M"), "id": e.get("id"),
                        "label": e.get("label") or e.get("command", "")[:48], "managed": e.get("managed")})
    occ.sort(key=lambda o: o["when"])
    by_day: dict = {}
    for o in occ:
        by_day.setdefault(o["date"], []).append(o)
    return {"days": days, "occurrences": occ, "byDay": by_day, "entryCount": len(ents)}


# --------------------------------------------------------------- calendar export (platform files)

# IFURI-035: formaty (ics/RRULE/CSV) = wspólne źródło w calendar-connectorze; cron DELEGUJE tu.
# Fallback (lokalna kopia) gdy calendar niedostępny — cron musi działać standalone.
try:  # pragma: no cover - zależne od instalacji
    from urirun_connector_calendar import formats as _fmt
except Exception:  # noqa: BLE001
    _fmt = None


def _freq_rule(fields: list[str]) -> str:
    """cron → RRULE. Deleguje do calendar.formats (wspólne quirki); fallback lokalny."""
    if _fmt is not None:
        return _fmt.cron_fields_to_rrule(fields)
    mn, hr, dom, mon, dow = fields
    if dow != "*" and dom == "*":
        days = {"0": "SU", "1": "MO", "2": "TU", "3": "WE", "4": "TH", "5": "FR", "6": "SA", "7": "SU"}
        by = ",".join(days.get(d, "MO") for d in dow.split(",") if d in days)
        return f"RRULE:FREQ=WEEKLY;BYDAY={by or 'MO'}"
    return "RRULE:FREQ=HOURLY" if hr == "*" else "RRULE:FREQ=DAILY"


def _ics(entries: list[dict], mode: str) -> str:
    """Buduje iCalendar. Deleguje envelope/format do calendar.formats, przekazując scheduler cron
    (_occurrences) jako źródło wystąpień — format nie zna schedulera. Fallback lokalny."""
    if _fmt is not None:
        return _fmt.build_ics(entries, mode, _occurrences)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ifURI//urirun-connector-cron//PL", "CALSCALE:GREGORIAN"]
    for e in entries:
        if len(e.get("fields") or []) != 5:
            continue
        uid_base = f"cron-{e.get('id') or abs(hash(e['schedule']))}@urirun"
        summary = (e.get("label") or e.get("command", "")[:60]).replace("\n", " ")
        if mode == "events":
            for i, t in enumerate(_occurrences(e, 30, 30)):
                lines += ["BEGIN:VEVENT", f"UID:{uid_base}-{i}", f"DTSTART:{t.strftime('%Y%m%dT%H%M%S')}",
                          "DURATION:PT1M", f"SUMMARY:{summary}",
                          f"DESCRIPTION:{e.get('command','')}", "END:VEVENT"]
        else:
            occ = _occurrences(e, 2, 1)
            if not occ:
                continue
            lines += ["BEGIN:VEVENT", f"UID:{uid_base}", f"DTSTART:{occ[0].strftime('%Y%m%dT%H%M%S')}",
                      "DURATION:PT1M", f"SUMMARY:{summary}", f"DESCRIPTION:{e.get('command','')}",
                      _freq_rule(e["fields"]), "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _google_csv(days: int) -> str:
    """Google CSV. Deleguje do calendar.formats; fallback lokalny."""
    occ = _calendar(days).get("occurrences", [])
    if _fmt is not None:
        return _fmt.build_google_csv(occ)
    rows = ["Subject,Start Date,Start Time,End Date,End Time,Description"]
    for o in occ:
        d = o["date"]
        rows.append(f"\"{o['label']}\",{d},{o['time']},{d},{o['time']},\"cron {o.get('id') or ''}\"")
    return "\n".join(rows) + "\n"


# --------------------------------------------------------------- IMPORT: .ics/CalDAV → cron (odwrotność _freq_rule)

_ICS_DAY = {"SU": "0", "MO": "1", "TU": "2", "WE": "3", "TH": "4", "FR": "5", "SA": "6"}


def _unfold_ics(text: str) -> list[str]:
    """RFC-5545: sklej linie kontynuacji (zaczynające się spacją/tab) w jedną logiczną."""
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        else:
            out.append(raw)
    return out


def _parse_ics_events(text: str) -> list[dict]:
    """Wyłuskaj VEVENT-y: DTSTART, RRULE, SUMMARY, DESCRIPTION (property przed ';'/':' bez parametrów)."""
    events, cur = [], None
    for line in _unfold_ics(text):
        s = line.strip()
        if s == "BEGIN:VEVENT":
            cur = {}
        elif s == "END:VEVENT" and cur is not None:
            events.append(cur)
            cur = None
        elif cur is not None and ":" in s:
            name = s.split(":", 1)[0].split(";", 1)[0].upper()
            val = s.split(":", 1)[1]
            if name in ("DTSTART", "RRULE", "SUMMARY", "DESCRIPTION"):
                cur[name] = val
    return events


def _rrule_to_cron(rrule: str, dtstart: str) -> str | None:
    """RRULE + DTSTART → 5-pole cron. DAILY→'M H * * *', WEEKLY;BYDAY→dni, HOURLY→'M * * * *',
    brak RRULE → jednorazowe 'M H D Mon *'. Odbicie _freq_rule (eksport↔import round-trip)."""
    digits = "".join(c for c in dtstart if c.isdigit())
    hh, mm = (digits[8:10] or "0"), (digits[10:12] or "0")
    minute, hour = str(int(mm)), str(int(hh))
    parts = dict(kv.split("=", 1) for kv in rrule.split(";") if "=" in kv) if rrule else {}
    freq = parts.get("FREQ", "").upper()
    interval = parts.get("INTERVAL", "1")
    if freq == "HOURLY":
        return f"{minute} {'*' if interval == '1' else '*/' + interval} * * *"
    if freq == "WEEKLY":
        by = [_ICS_DAY[d] for d in parts.get("BYDAY", "").split(",") if d in _ICS_DAY]
        return f"{minute} {hour} * * {','.join(by) if by else '*'}"
    if freq == "DAILY":
        return f"{minute} {hour} {'*' if interval == '1' else '*/' + interval} * *"
    if not rrule and len(digits) >= 8:  # jednorazowe wg DTSTART
        return f"{minute} {hour} {int(digits[6:8])} {int(digits[4:6])} *"
    return None


def _ics_to_entries(text: str) -> list[dict]:
    """VEVENT-y → propozycje wpisów cron {schedule, command, label}. command z DESCRIPTION→SUMMARY."""
    out = []
    for ev in _parse_ics_events(text):
        cron = _rrule_to_cron(ev.get("RRULE", ""), ev.get("DTSTART", ""))
        if not cron:
            continue
        label = (ev.get("SUMMARY") or "").strip()
        command = (ev.get("DESCRIPTION") or label or "").strip()
        if command:
            out.append({"schedule": cron, "command": command, "label": label})
    return out


# --------------------------------------------------------------- handlers

@conn.handler("entry/query/list", isolated=False, meta={"label": "List cron entries (managed + others)"})
def entry_query_list() -> dict[str, Any]:
    try:
        return _ok(action="cron-list", entries=_entries())
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc), "cron-list")


@conn.handler("calendar/query/upcoming", isolated=False, meta={"label": "Upcoming scheduled runs (calendar)"})
def calendar_query_upcoming(days: int = 7) -> dict[str, Any]:
    try:
        return _ok(action="cron-calendar", **_calendar(int(days)))
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc), "cron-calendar")


@conn.handler("entry/command/add", isolated=True, meta={"label": "Add a managed cron entry (5-field or 'codziennie 08:00')"})
def entry_command_add(schedule: str = "", command: str = "", label: str = "") -> dict[str, Any]:
    cron = human_to_cron(schedule)
    if not cron:
        return _fail("harmonogram = 5 pól cron lub np. 'codziennie 08:00'", "cron-add")
    if not (command or "").strip():
        return _fail("polecenie jest wymagane", "cron-add")
    lines = _read()
    cid = _gen_id({e["id"] for e in _entries() if e.get("id")})
    lines.append(f"{cron} {command.strip()} # urirun:{cid} {label}".rstrip())
    ok, err = _write(lines)
    return _ok(action="cron-add", id=cid, cron=cron) if ok else _fail(err or "crontab write failed", "cron-add")


@conn.handler("entry/command/edit", isolated=True, meta={"label": "Edit a managed cron entry by id"})
def entry_command_edit(id: str = "", schedule: str = "", command: str = "", label: str | None = None) -> dict[str, Any]:
    cid = (id or "").strip()
    out, hit = [], False
    for l in _read():
        e = _parse(l)
        if e and e.get("id") == cid:
            cron = human_to_cron(schedule) if schedule else e["schedule"]
            if not cron:
                return _fail("zły harmonogram", "cron-edit")
            lab = e["label"] if label is None else label
            out.append(f"{cron} {command.strip() if command else e['command']} # urirun:{cid} {lab}".rstrip())
            hit = True
        else:
            out.append(l)
    if not hit:
        return _fail(f"brak zarządzanego wpisu {cid}", "cron-edit")
    ok, err = _write(out)
    return _ok(action="cron-edit", id=cid) if ok else _fail(err or "write failed", "cron-edit")


@conn.handler("entry/command/remove", isolated=True, meta={"label": "Remove a managed cron entry by id"})
def entry_command_remove(id: str = "") -> dict[str, Any]:
    cid = (id or "").strip()
    lines = _read()
    out = [l for l in lines if (_parse(l) or {}).get("id") != cid]
    if len(out) == len(lines):
        return _fail(f"brak zarządzanego wpisu {cid}", "cron-remove")
    ok, err = _write(out)
    return _ok(action="cron-remove", id=cid) if ok else _fail(err or "write failed", "cron-remove")


@conn.handler("export/query/ics", isolated=False,
              meta={"label": "Export cron schedules to iCalendar (.ics) — all or one id; mode=rrule|events"})
def export_query_ics(id: str = "", mode: str = "rrule", days: int = 30) -> dict[str, Any]:
    try:
        ents = [e for e in _entries() if (not id or e.get("id") == id)]
        text = _ics(ents, "events" if mode == "events" else "rrule")
        return _ok(action="cron-export-ics", contentType="text/calendar", filename="urirun-cron.ics",
                   ics=text, bytes=len(text), events=text.count("BEGIN:VEVENT"))
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc), "cron-export-ics")


@conn.handler("export/query/google-csv", isolated=False,
              meta={"label": "Export upcoming runs to Google Calendar CSV"})
def export_query_google_csv(days: int = 14) -> dict[str, Any]:
    try:
        text = _google_csv(int(days))
        return _ok(action="cron-export-gcsv", contentType="text/csv",
                   filename="urirun-cron-google.csv", csv=text, bytes=len(text))
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc), "cron-export-gcsv")


def _fetch_ics(url: str) -> str:
    """CalDAV/webcal/https → tekst iCalendar (stdlib, webcal→https, nigdy nie rzuca)."""
    import urllib.request
    u = url.replace("webcal://", "https://", 1)
    with urllib.request.urlopen(u, timeout=15) as r:  # noqa: S310
        return r.read().decode("utf-8", "replace")


@conn.handler("import/command/ics", isolated=True,
              meta={"label": "Import .ics/CalDAV (VEVENT+RRULE) → wpisy cron; add=False = dry-run podgląd"})
def import_command_ics(ics: str = "", url: str = "", add: bool = False) -> dict[str, Any]:
    """Parsuj iCalendar (tekst ``ics`` albo pobrany z ``url``/CalDAV) i zmapuj na wpisy cron.
    add=False → tylko podgląd propozycji; add=True → zapisz jako zarządzane wpisy (odwracalne: remove)."""
    try:
        text = ics or (_fetch_ics(url) if url else "")
        if not text.strip():
            return _fail("podaj 'ics' (tekst) albo 'url' (CalDAV/webcal/https)", "cron-import-ics")
        proposals = _ics_to_entries(text)
        if not add:
            return _ok(action="cron-import-ics", dry_run=True, count=len(proposals), proposals=proposals)
        added = []
        for p in proposals:
            r = entry_command_add(schedule=p["schedule"], command=p["command"], label=p.get("label", ""))
            if r.get("ok"):
                added.append({"id": r.get("id"), "cron": r.get("cron"), "command": p["command"]})
        return _ok(action="cron-import-ics", dry_run=False, added=added, count=len(added))
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc), "cron-import-ics")


@conn.handler("import/command/caldav", isolated=True,
              meta={"label": "Import feedu CalDAV/webcal (URL) → wpisy cron; add=False = dry-run podgląd"})
def import_command_caldav(url: str = "", add: bool = False) -> dict[str, Any]:
    """CalDAV/webcal feed z URL → cron. Deleguje do import_command_ics (pobiera przez _fetch_ics,
    parsuje VEVENT+RRULE). add=False → podgląd; add=True → zapis zarządzanych wpisów (odwracalne)."""
    if not (url or "").strip():
        return _fail("url (CalDAV/webcal/https) wymagany", "cron-import-caldav")
    r = import_command_ics(url=url, add=add)
    if isinstance(r, dict) and r.get("ok"):
        r["action"] = "cron-import-caldav"
    return r


def urirun_bindings() -> dict[str, Any]:
    return conn.bindings()


def connector_manifest() -> dict[str, Any]:
    return urirun.load_manifest(__package__) or {"id": CONNECTOR_ID}


def main(argv: list[str] | None = None) -> int:
    return conn.cli(argv, manifest_prose=urirun.load_manifest(__package__))


if __name__ == "__main__":
    raise SystemExit(main())
