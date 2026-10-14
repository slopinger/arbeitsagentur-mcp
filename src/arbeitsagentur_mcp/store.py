"""Local case file ("Akte") for one customer of the Agentur für Arbeit / Jobcenter.

Personal data never leaves the machine: it is kept in a SQLite file (mode 0600) under
$ARBEITSAGENTUR_MCP_DB, or $XDG_DATA_HOME/arbeitsagentur-mcp/akte.sqlite3 by default.
"""

from __future__ import annotations

import csv
import io
import os
import sqlite3
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

PROFILE_FIELDS: dict[str, str] = {
    "name": "Vor- und Nachname",
    "address": "Anschrift (Straße, PLZ Ort)",
    "birth_date": "Geburtsdatum (YYYY-MM-DD)",
    "phone": "Telefonnummer",
    "email": "E-Mail-Adresse",
    "customer_number": "Kundennummer der Agentur für Arbeit (steht auf jedem Schreiben)",
    "bg_number": "Nummer der Bedarfsgemeinschaft (Jobcenter, SGB II)",
    "benefit": "Leistung: 'alg' (Arbeitslosengeld, SGB III), 'grundsicherung' (Bürgergeld/Grundsicherung, SGB II) oder 'keine'",
    "agency": "Zuständige Agentur für Arbeit (Name, Anschrift)",
    "jobcenter": "Zuständiges Jobcenter (Name, Anschrift)",
    "counselor": "Ansprechpartner/in (Vermittlungsfachkraft / Integrationsfachkraft)",
    "counselor_contact": "Durchwahl / E-Mail / Teamadresse der Ansprechperson",
    "state": "Bundesland (für Feiertage bei Fristen, z. B. 'BY')",
    "employment_end": "Ende des letzten Beschäftigungsverhältnisses (YYYY-MM-DD)",
    "termination_known_on": "Tag, an dem das Ende bekannt wurde, z. B. Zugang der Kündigung (YYYY-MM-DD)",
    "registered_job_seeking_on": "Datum der Arbeitsuchendmeldung (YYYY-MM-DD)",
    "registered_unemployed_on": "Datum der Arbeitslosmeldung (YYYY-MM-DD)",
    "benefit_start": "Leistungsbeginn laut Bescheid (YYYY-MM-DD)",
    "benefit_end": "Voraussichtliches Leistungsende laut Bescheid (YYYY-MM-DD)",
    "daily_rate_eur": "Tagessatz Arbeitslosengeld laut Bescheid (EUR)",
    "applications_per_month": "Vereinbarte Mindestzahl Bewerbungen pro Monat (Kooperationsplan / Eingliederungsvereinbarung)",
    "target_jobs": "Zielberufe / gesuchte Stellen",
    "notes": "Freie Notizen",
}

APPLICATION_STATUSES = ["geplant", "beworben", "eingangsbestaetigung", "vorstellungsgespraech", "zusage", "absage",
                        "zurueckgezogen", "keine_antwort"]
APPLICATION_SOURCES = ["eigeninitiative", "jobboerse", "vermittlungsvorschlag", "netzwerk", "sonstige"]
APPLICATION_CHANNELS = ["online", "email", "post", "persoenlich", "telefon", "portal"]
APPOINTMENT_KINDS = ["meldetermin", "beratung", "aerztlicher_dienst", "psychologischer_dienst", "massnahme",
                     "vorstellungsgespraech", "infoveranstaltung", "sonstige"]
APPOINTMENT_STATUSES = ["geplant", "wahrgenommen", "abgesagt", "verlegt", "versaeumt"]
CORRESPONDENCE_KINDS = ["bescheid", "einladung", "vermittlungsvorschlag", "anhoerung", "aufforderung", "kooperationsplan",
                        "brief", "widerspruch", "antrag", "nachricht", "telefonat", "gespraech", "sonstige"]
CHANNELS = ["post", "eservice", "email", "telefon", "persoenlich", "fax"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    applied_on TEXT,
    employer TEXT NOT NULL,
    employer_address TEXT,
    position TEXT NOT NULL,
    reference_number TEXT,
    job_url TEXT,
    source TEXT NOT NULL DEFAULT 'eigeninitiative',
    channel TEXT,
    contact_person TEXT,
    status TEXT NOT NULL DEFAULT 'beworben',
    status_date TEXT,
    proposal_received_on TEXT,
    apply_by TEXT,
    result_reported_on TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    location TEXT,
    with_whom TEXT,
    purpose TEXT,
    status TEXT NOT NULL DEFAULT 'geplant',
    invitation_date TEXT,
    bring TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS correspondence (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    date TEXT NOT NULL,
    direction TEXT NOT NULL,
    kind TEXT NOT NULL,
    channel TEXT,
    counterpart TEXT,
    subject TEXT NOT NULL,
    reference TEXT,
    summary TEXT,
    received_on TEXT,
    objection_deadline TEXT,
    objection_status TEXT,
    file_path TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    title TEXT NOT NULL,
    due TEXT,
    source TEXT,
    related TEXT,
    done_on TEXT,
    notes TEXT
);
"""

TABLES = {
    "application": "applications",
    "appointment": "appointments",
    "correspondence": "correspondence",
    "task": "tasks",
}


def default_db_path() -> Path:
    env = os.environ.get("ARBEITSAGENTUR_MCP_DB")
    if env:
        return Path(env).expanduser()
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "arbeitsagentur-mcp" / "akte.sqlite3"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_date(value: str | date | None, field: str = "date") -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    v = value.strip()
    for f in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(v, f).date()
        except ValueError:
            pass
    raise ValueError(f"{field}: expected a date like 2026-10-14 or 14.10.2026, got {value!r}")


def parse_datetime(value: str, field: str = "starts_at") -> datetime:
    v = value.strip().replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        pass
    for f in ("%d.%m.%YT%H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(v, f)
        except ValueError:
            pass
    raise ValueError(f"{field}: expected a date-time like 2026-10-20T09:30 or '20.10.2026 09:30', got {value!r}")


def _check(value: str | None, allowed: list[str], field: str) -> str | None:
    if value is None:
        return None
    v = value.strip().lower()
    if v not in allowed:
        raise ValueError(f"{field} must be one of: {', '.join(allowed)}")
    return v


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


class Store:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        new = not self.path.exists()
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        if new:
            os.chmod(self.path, 0o600)

    def close(self) -> None:
        self.db.close()

    # --- generic helpers ------------------------------------------------------------------

    def _insert(self, table: str, values: dict[str, Any]) -> dict[str, Any]:
        values = {k: v for k, v in values.items() if v is not None}
        values["created_at"] = values["updated_at"] = _now()
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        cur = self.db.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(values.values()))
        return self.get(table, cur.lastrowid)

    def _update(self, table: str, row_id: int, values: dict[str, Any]) -> dict[str, Any]:
        self.get(table, row_id)
        values = {k: v for k, v in values.items() if v is not None}
        if values:
            values["updated_at"] = _now()
            sets = ", ".join(f"{k} = ?" for k in values)
            self.db.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*values.values(), row_id])
        return self.get(table, row_id)

    def get(self, table: str, row_id: int) -> dict[str, Any]:
        row = self.db.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            raise KeyError(f"No entry #{row_id} in {table}")
        return {k: row[k] for k in row.keys() if row[k] is not None}

    def _select(self, sql: str, args: Iterable[Any] = ()) -> list[dict[str, Any]]:
        return [{k: r[k] for k in r.keys() if r[k] is not None} for r in self.db.execute(sql, list(args))]

    def delete(self, kind: str, row_id: int) -> dict[str, Any]:
        table = TABLES.get(kind)
        if table is None:
            raise ValueError(f"kind must be one of {', '.join(TABLES)}")
        row = self.get(table, row_id)
        self.db.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
        return row

    # --- profile --------------------------------------------------------------------------

    def profile(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self.db.execute("SELECT key, value FROM profile ORDER BY key")}

    def update_profile(self, values: dict[str, Any]) -> dict[str, str]:
        unknown = set(values) - set(PROFILE_FIELDS)
        if unknown:
            raise ValueError(f"Unknown profile field(s): {', '.join(sorted(unknown))}")
        for key, value in values.items():
            if value is None:
                continue
            if key in {"birth_date", "employment_end", "termination_known_on", "registered_job_seeking_on",
                       "registered_unemployed_on", "benefit_start", "benefit_end"} and value != "":
                value = parse_date(value, key).isoformat()
            if value == "":
                self.db.execute("DELETE FROM profile WHERE key = ?", (key,))
            else:
                self.db.execute("INSERT INTO profile (key, value) VALUES (?, ?) "
                                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
        return self.profile()

    # --- applications ---------------------------------------------------------------------

    def add_application(
        self,
        *,
        employer: str,
        position: str,
        applied_on: str | None = None,
        source: str = "eigeninitiative",
        channel: str | None = None,
        status: str | None = None,
        employer_address: str | None = None,
        reference_number: str | None = None,
        job_url: str | None = None,
        contact_person: str | None = None,
        proposal_received_on: str | None = None,
        apply_by: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        source = _check(source, APPLICATION_SOURCES, "source")
        applied = parse_date(applied_on, "applied_on")
        status = _check(status, APPLICATION_STATUSES, "status") or ("beworben" if applied else "geplant")
        if status != "geplant" and applied is None:
            applied = date.today()
        received = parse_date(proposal_received_on, "proposal_received_on")
        deadline = parse_date(apply_by, "apply_by")
        if source == "vermittlungsvorschlag" and received is None:
            received = date.today() if applied is None else applied
        if source == "vermittlungsvorschlag" and deadline is None and status == "geplant":
            deadline = received + timedelta(days=3)
        row = self._insert("applications", {
            "employer": employer.strip(),
            "position": position.strip(),
            "applied_on": _iso(applied),
            "source": source,
            "channel": _check(channel, APPLICATION_CHANNELS, "channel"),
            "status": status,
            "status_date": _iso(applied) if status != "geplant" else None,
            "employer_address": employer_address,
            "reference_number": reference_number,
            "job_url": job_url,
            "contact_person": contact_person,
            "proposal_received_on": _iso(received),
            "apply_by": _iso(deadline),
            "notes": notes,
        })
        return row

    def update_application(self, application_id: int, **fields: Any) -> dict[str, Any]:
        current = self.get("applications", application_id)
        values: dict[str, Any] = {}
        for key, value in fields.items():
            if value is None:
                continue
            if key == "status":
                values["status"] = _check(value, APPLICATION_STATUSES, "status")
                values.setdefault("status_date", date.today().isoformat())
                if values["status"] != "geplant" and "applied_on" not in current and "applied_on" not in fields:
                    values["applied_on"] = date.today().isoformat()
            elif key == "source":
                values[key] = _check(value, APPLICATION_SOURCES, key)
            elif key == "channel":
                values[key] = _check(value, APPLICATION_CHANNELS, key)
            elif key in {"applied_on", "status_date", "proposal_received_on", "apply_by", "result_reported_on"}:
                values[key] = _iso(parse_date(value, key))
            elif key in {"employer", "employer_address", "position", "reference_number", "job_url",
                         "contact_person", "notes"}:
                values[key] = value
            else:
                raise ValueError(f"Unknown application field {key!r}")
        return self._update("applications", application_id, values)

    def list_applications(
        self,
        *,
        status: str | None = None,
        source: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        where, args = [], []
        if status:
            where.append("status = ?")
            args.append(_check(status, APPLICATION_STATUSES, "status"))
        if source:
            where.append("source = ?")
            args.append(_check(source, APPLICATION_SOURCES, "source"))
        if since:
            where.append("COALESCE(applied_on, created_at) >= ?")
            args.append(parse_date(since, "since").isoformat())
        if until:
            where.append("COALESCE(applied_on, substr(created_at, 1, 10)) <= ?")
            args.append(parse_date(until, "until").isoformat())
        sql = "SELECT * FROM applications"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY COALESCE(applied_on, created_at) DESC, id DESC LIMIT ?"
        return self._select(sql, [*args, limit])

    def proof_of_applications(self, since: str, until: str, fmt: str = "markdown") -> str:
        """'Nachweis der Eigenbemühungen' for a period, as a Markdown table or CSV."""
        start, end = parse_date(since, "since"), parse_date(until, "until")
        rows = self._select(
            "SELECT * FROM applications WHERE applied_on IS NOT NULL AND applied_on BETWEEN ? AND ? "
            "AND status != 'geplant' ORDER BY applied_on, id",
            (start.isoformat(), end.isoformat()),
        )
        header = ["Nr.", "Datum", "Arbeitgeber (Name, Anschrift)", "Stelle / Referenznummer", "Art der Bewerbung",
                  "Herkunft", "Ansprechpartner", "Ergebnis / Stand"]
        lines = []
        for i, r in enumerate(rows, 1):
            employer = r["employer"] + (f", {r['employer_address']}" if r.get("employer_address") else "")
            pos = r["position"] + (f" (Ref. {r['reference_number']})" if r.get("reference_number") else "")
            result = r["status"] + (f" ({_de(r['status_date'])})" if r.get("status_date") and r["status"] != "beworben" else "")
            lines.append([str(i), _de(r["applied_on"]), employer, pos, r.get("channel") or "", r["source"],
                          r.get("contact_person") or "", result])
        profile = self.profile()
        if fmt == "csv":
            buf = io.StringIO()
            w = csv.writer(buf, delimiter=";")
            w.writerow(header)
            w.writerows(lines)
            return buf.getvalue()
        if fmt != "markdown":
            raise ValueError("format must be 'markdown' or 'csv'")
        out = [f"# Nachweis der Eigenbemühungen {_de(start.isoformat())} – {_de(end.isoformat())}", ""]
        if profile.get("name"):
            out.append(f"**Name:** {profile['name']}  ")
        if profile.get("customer_number"):
            out.append(f"**Kundennummer:** {profile['customer_number']}  ")
        if profile.get("bg_number"):
            out.append(f"**BG-Nummer:** {profile['bg_number']}  ")
        out += [f"**Anzahl Bewerbungen:** {len(rows)}", ""]
        out.append("| " + " | ".join(header) + " |")
        out.append("|" + "|".join("---" for _ in header) + "|")
        for line in lines:
            out.append("| " + " | ".join(c.replace("|", "/").replace("\n", " ") for c in line) + " |")
        if not lines:
            out.append("| " + " | ".join(["–"] * len(header)) + " |")
        out += ["", f"Erstellt am {_de(date.today().isoformat())}. Ich versichere die Richtigkeit der Angaben.", "",
                "Unterschrift: ______________________"]
        return "\n".join(out) + "\n"

    # --- appointments ---------------------------------------------------------------------

    def add_appointment(self, *, starts_at: str, kind: str, location: str | None = None, with_whom: str | None = None,
                        purpose: str | None = None, invitation_date: str | None = None, bring: str | None = None,
                        notes: str | None = None) -> dict[str, Any]:
        return self._insert("appointments", {
            "starts_at": parse_datetime(starts_at).isoformat(timespec="minutes"),
            "kind": _check(kind, APPOINTMENT_KINDS, "kind"),
            "location": location,
            "with_whom": with_whom,
            "purpose": purpose,
            "invitation_date": _iso(parse_date(invitation_date, "invitation_date")),
            "bring": bring,
            "notes": notes,
            "status": "geplant",
        })

    def update_appointment(self, appointment_id: int, **fields: Any) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, value in fields.items():
            if value is None:
                continue
            if key == "starts_at":
                values[key] = parse_datetime(value).isoformat(timespec="minutes")
            elif key == "status":
                values[key] = _check(value, APPOINTMENT_STATUSES, key)
            elif key == "kind":
                values[key] = _check(value, APPOINTMENT_KINDS, key)
            elif key == "invitation_date":
                values[key] = _iso(parse_date(value, key))
            elif key in {"location", "with_whom", "purpose", "bring", "notes"}:
                values[key] = value
            else:
                raise ValueError(f"Unknown appointment field {key!r}")
        return self._update("appointments", appointment_id, values)

    def list_appointments(self, *, upcoming_only: bool = True, limit: int = 100) -> list[dict[str, Any]]:
        if upcoming_only:
            return self._select("SELECT * FROM appointments WHERE starts_at >= ? AND status = 'geplant' "
                                "ORDER BY starts_at LIMIT ?", (date.today().isoformat(), limit))
        return self._select("SELECT * FROM appointments ORDER BY starts_at DESC LIMIT ?", (limit,))

    # --- correspondence -------------------------------------------------------------------

    def add_correspondence(self, **fields: Any) -> dict[str, Any]:
        values = dict(fields)
        values["date"] = parse_date(values["date"], "date").isoformat()
        values["direction"] = _check(values.get("direction") or "eingang", ["eingang", "ausgang"], "direction")
        values["kind"] = _check(values["kind"], CORRESPONDENCE_KINDS, "kind")
        values["channel"] = _check(values.get("channel"), CHANNELS, "channel")
        values["received_on"] = _iso(parse_date(values.get("received_on"), "received_on"))
        values["objection_deadline"] = _iso(parse_date(values.get("objection_deadline"), "objection_deadline"))
        return self._insert("correspondence", values)

    def update_correspondence(self, entry_id: int, **fields: Any) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, value in fields.items():
            if value is None:
                continue
            if key == "objection_status":
                values[key] = _check(value, ["offen", "eingelegt", "verzichtet", "erledigt"], key)
            elif key in {"date", "received_on", "objection_deadline"}:
                values[key] = _iso(parse_date(value, key))
            elif key in {"subject", "reference", "summary", "file_path", "notes", "counterpart"}:
                values[key] = value
            else:
                raise ValueError(f"Unknown correspondence field {key!r}")
        return self._update("correspondence", entry_id, values)

    def list_correspondence(self, *, kind: str | None = None, since: str | None = None, query: str | None = None,
                            limit: int = 100) -> list[dict[str, Any]]:
        where, args = [], []
        if kind:
            where.append("kind = ?")
            args.append(_check(kind, CORRESPONDENCE_KINDS, "kind"))
        if since:
            where.append("date >= ?")
            args.append(parse_date(since, "since").isoformat())
        if query:
            where.append("(subject LIKE ? OR summary LIKE ? OR reference LIKE ? OR notes LIKE ?)")
            args += [f"%{query}%"] * 4
        sql = "SELECT * FROM correspondence"
        if where:
            sql += " WHERE " + " AND ".join(where)
        return self._select(sql + " ORDER BY date DESC, id DESC LIMIT ?", [*args, limit])

    # --- tasks ----------------------------------------------------------------------------

    def add_task(self, *, title: str, due: str | None = None, source: str | None = None, related: str | None = None,
                 notes: str | None = None) -> dict[str, Any]:
        return self._insert("tasks", {"title": title, "due": _iso(parse_date(due, "due")), "source": source,
                                      "related": related, "notes": notes})

    def complete_task(self, task_id: int, done_on: str | None = None, notes: str | None = None) -> dict[str, Any]:
        return self._update("tasks", task_id, {"done_on": _iso(parse_date(done_on, "done_on")) or date.today().isoformat(),
                                               "notes": notes})

    def list_tasks(self, *, include_done: bool = False, limit: int = 200) -> list[dict[str, Any]]:
        sql = "SELECT * FROM tasks"
        if not include_done:
            sql += " WHERE done_on IS NULL"
        return self._select(sql + " ORDER BY due IS NULL, due, id LIMIT ?", (limit,))

    # --- overview -------------------------------------------------------------------------

    def overview(self, today: date | None = None, horizon_days: int = 14) -> dict[str, Any]:
        today = today or date.today()
        horizon = today + timedelta(days=horizon_days)
        profile = self.profile()
        alerts: list[str] = []

        appts = self._select("SELECT * FROM appointments WHERE status = 'geplant' AND starts_at >= ? "
                             "ORDER BY starts_at", (today.isoformat(),))
        upcoming = [a for a in appts if a["starts_at"][:10] <= horizon.isoformat()]
        past_open = self._select("SELECT * FROM appointments WHERE status = 'geplant' AND starts_at < ? "
                                 "ORDER BY starts_at", (today.isoformat(),))
        for a in past_open:
            alerts.append(f"Termin #{a['id']} am {_de(a['starts_at'][:10])} ({a['kind']}) steht noch auf 'geplant' - "
                          "Status nachtragen (wahrgenommen/abgesagt/verlegt/versaeumt).")

        deadlines: list[dict[str, Any]] = []
        for c in self._select("SELECT * FROM correspondence WHERE objection_deadline IS NOT NULL "
                              "AND COALESCE(objection_status, 'offen') = 'offen' ORDER BY objection_deadline"):
            d = parse_date(c["objection_deadline"])
            deadlines.append({"due": c["objection_deadline"], "days_left": (d - today).days,
                              "what": f"Widerspruchsfrist: {c['subject']} (Eintrag #{c['id']})"})
        for t in self.list_tasks():
            if t.get("due"):
                d = parse_date(t["due"])
                deadlines.append({"due": t["due"], "days_left": (d - today).days, "what": f"Aufgabe #{t['id']}: {t['title']}"})
        for a in self._select("SELECT * FROM applications WHERE source = 'vermittlungsvorschlag' AND status = 'geplant'"):
            due = a.get("apply_by")
            deadlines.append({"due": due, "days_left": (parse_date(due) - today).days if due else None,
                              "what": f"Bewerbung auf Vermittlungsvorschlag #{a['id']}: {a['position']} bei {a['employer']}"})
        deadlines.sort(key=lambda x: (x["due"] is None, x["due"] or ""))
        for d in deadlines:
            if d["days_left"] is not None and d["days_left"] < 0:
                alerts.append(f"ÜBERFÄLLIG seit {-d['days_left']} Tag(en): {d['what']}")
            elif d["days_left"] is not None and d["days_left"] <= 3:
                alerts.append(f"Fällig in {d['days_left']} Tag(en): {d['what']}")

        unreported = self._select(
            "SELECT * FROM applications WHERE source = 'vermittlungsvorschlag' AND status IN "
            "('zusage', 'absage', 'zurueckgezogen', 'keine_antwort', 'vorstellungsgespraech') AND result_reported_on IS NULL")
        for a in unreported:
            alerts.append(f"Ergebnis des Vermittlungsvorschlags #{a['id']} ({a['position']} bei {a['employer']}: "
                          f"{a['status']}) ist der Agentur noch nicht zurückgemeldet.")

        month_start = today.replace(day=1)
        this_month = self.db.execute(
            "SELECT COUNT(*) FROM applications WHERE status != 'geplant' AND applied_on >= ?",
            (month_start.isoformat(),)).fetchone()[0]
        stats = {
            "applications_this_month": this_month,
            "by_status": {r[0]: r[1] for r in self.db.execute("SELECT status, COUNT(*) FROM applications GROUP BY status")},
        }
        required = profile.get("applications_per_month")
        if required and required.isdigit():
            stats["required_per_month"] = int(required)
            missing = int(required) - this_month
            if missing > 0:
                stats["missing_this_month"] = missing
                next_month = (month_start + timedelta(days=32)).replace(day=1)
                days_left = (next_month - today).days
                alerts.append(f"Noch {missing} Bewerbung(en) bis Monatsende nötig ({days_left} Tage verbleiben).")
        stale_cutoff = (today - timedelta(days=28)).isoformat()
        stale = self._select("SELECT id, employer, position, applied_on FROM applications WHERE status IN "
                             "('beworben', 'eingangsbestaetigung') AND applied_on <= ? ORDER BY applied_on", (stale_cutoff,))
        if stale:
            stats["no_answer_for_4_weeks"] = stale

        reg = []
        if profile.get("employment_end") and not profile.get("registered_job_seeking_on"):
            reg.append("Arbeitsuchendmeldung ist nicht als erledigt eingetragen (registration_deadlines prüfen).")
        if profile.get("employment_end") and not profile.get("registered_unemployed_on"):
            end = parse_date(profile["employment_end"])
            if end and end - today <= timedelta(days=90):
                reg.append(f"Arbeitslosmeldung spätestens am {_de((end + timedelta(days=1)).isoformat())} "
                           "(noch nicht als erledigt eingetragen).")
        alerts = reg + alerts
        if profile.get("benefit_end"):
            end = parse_date(profile["benefit_end"])
            if end and 0 <= (end - today).days <= 90:
                alerts.append(f"Leistungsanspruch endet am {_de(end.isoformat())} - Anschlussleistung (z. B. Grundsicherung "
                              "beim Jobcenter) rechtzeitig beantragen.")

        missing_profile = [k for k in ("name", "customer_number", "benefit", "state") if k not in profile]
        return {
            "today": today.isoformat(),
            "alerts": alerts,
            "upcoming_appointments": upcoming,
            "later_appointments": len(appts) - len(upcoming),
            "deadlines": deadlines,
            "applications": stats,
            "profile_missing": missing_profile,
            "database": str(self.path),
        }


def _de(iso: str | None) -> str:
    if not iso:
        return ""
    d = parse_date(iso[:10])
    return d.strftime("%d.%m.%Y") if d else iso
