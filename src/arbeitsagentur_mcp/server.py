"""MCP server: arbeitsagentur.de as seen from the customer's side."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from . import __version__, deadlines, guide, letters
from .api import BAClient, BAError
from .meineba import POSTFACH_FOLDERS, SERVICES, WATCHLIST_STATUSES, MeineBA, MeineBAError
from .store import (
    APPLICATION_CHANNELS,
    APPLICATION_SOURCES,
    APPLICATION_STATUSES,
    APPOINTMENT_KINDS,
    APPOINTMENT_STATUSES,
    CHANNELS,
    CORRESPONDENCE_KINDS,
    PROFILE_FIELDS,
    Store,
    parse_date,
)

INSTRUCTIONS = f"""\
Helps a customer of the German Bundesagentur für Arbeit (Agentur für Arbeit / Jobcenter) manage
their case: job and course search, occupation and salary information, a local case file
(Bewerbungen, Termine, Schriftverkehr, Fristen, Aufgaben) and letter drafts.

Two kinds of tools:
1. Live public data from arbeitsagentur.de / mein-now.de (no login): search_jobs, get_job,
   search_courses, get_course, search_professions, get_profession, get_salaries, find_offices.
2. The user's private case file, stored only locally: profile, applications, appointments,
   correspondence, tasks, plus deadline calculators and letter drafts.

3. The user's own "Meine BA" account (meineba_* tools): Postfach, Termine, Verlauf, Anträge,
   Leistungen, Jobsuche-Merkliste. The user logs in themselves in their own browser
   (meineba_login_start -> open link -> paste the final address into meineba_login_finish); never
   ask for their password. Each service needs its own login; after the first one, single sign-on
   makes the others instant. Sending a Postfach message requires the user's explicit confirmation
   (confirm=true only after they approved the exact text).
Letters from draft_letter are drafts for the user to check, sign and send themselves. Explain rules with
`rules` and calculate deadlines with the calculators instead of from memory. Present deadlines
together with the reasoning and recommend acting before the last day. This is general information,
not legal advice; for disputes point to Sozialverbände, Gewerkschaften, Beratungsstellen or a
Fachanwalt für Sozialrecht (Beratungshilfe).

Start with `overview` to see what is due. Fill the profile (update_profile) early: customer number,
benefit type and Bundesland are used by letters and deadline calculations.
Valid profile fields: {", ".join(PROFILE_FIELDS)}.
"""

RO = ToolAnnotations(readOnlyHint=True, openWorldHint=True, idempotentHint=True)
LOCAL_RO = ToolAnnotations(readOnlyHint=True, openWorldHint=False, idempotentHint=True)
LOCAL_RW = ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False)
LOCAL_DEL = ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=True)


def _err(e: Exception) -> ToolError:
    """Errors raised as ToolError reach the client with their message; others become a generic error."""
    return ToolError(str(e))


def create_server(store: Store | None = None, client: BAClient | None = None,
                  meineba: MeineBA | None = None) -> MCPServer:
    mcp = MCPServer(
        name="arbeitsagentur",
        title="Arbeitsagentur (Kundensicht)",
        instructions=INSTRUCTIONS,
        version=__version__,
        website_url="https://git.freifick.net/slop/arbeitsagentur-mcp",
    )
    state: dict[str, Any] = {"store": store, "client": client, "meineba": meineba}

    def db() -> Store:
        if state["store"] is None:
            state["store"] = Store()
        return state["store"]

    def ba() -> BAClient:
        if state["client"] is None:
            state["client"] = BAClient()
        return state["client"]

    def mba() -> MeineBA:
        if state["meineba"] is None:
            state["meineba"] = MeineBA()
        return state["meineba"]

    def user_state(explicit: str | None) -> str | None:
        return deadlines.normalize_state(explicit or db().profile().get("state"))

    # ---------------------------------------------------------------------------------------
    # Public data
    # ---------------------------------------------------------------------------------------

    @mcp.tool(annotations=RO)
    async def search_jobs(
        what: Annotated[str | None, Field(description="Job title, skill or keyword, e.g. 'Pflegefachkraft' or 'Python'")] = None,
        where: Annotated[str | None, Field(description="Town or postcode, e.g. 'Leipzig' or '04109'")] = None,
        radius_km: Annotated[int | None, Field(description="Search radius around `where` in km", ge=0, le=200)] = None,
        offer_type: Annotated[Literal["arbeit", "ausbildung", "praktikum", "selbstaendigkeit"] | None,
                              Field(description="Type of offer; default all")] = None,
        working_time: Annotated[list[Literal["vollzeit", "teilzeit", "schicht", "homeoffice", "minijob"]] | None,
                                Field(description="Any of these working-time models")] = None,
        published_since_days: Annotated[int | None, Field(ge=0, le=100, description="Only offers published in the last N days")] = None,
        fixed_term: Annotated[bool | None, Field(description="true = only fixed-term, false = only permanent")] = None,
        temp_agencies: Annotated[bool | None, Field(description="false excludes Zeitarbeit")] = None,
        private_agencies: Annotated[bool | None, Field(description="false excludes private Arbeitsvermittlung")] = None,
        employer: Annotated[str | None, Field(description="Exact employer name, e.g. 'Deutsche Bahn AG'")] = None,
        page: Annotated[int, Field(ge=1)] = 1,
        size: Annotated[int, Field(ge=1, le=100)] = 25,
    ) -> dict[str, Any]:
        """Search the Jobbörse of the Bundesagentur für Arbeit (jobs, apprenticeships, internships).

        Returns condensed offers with `reference_number`; use get_job for the full ad and
        add_application to record an application.
        """
        try:
            return await ba().search_jobs(what, where, radius_km=radius_km, offer_type=offer_type,
                                          working_time=list(working_time) if working_time else None,
                                          published_since_days=published_since_days, fixed_term=fixed_term,
                                          temp_agencies=temp_agencies, private_agencies=private_agencies,
                                          employer=employer, page=page, size=size)
        except (BAError, ValueError) as e:
            raise _err(e) from e

    @mcp.tool(annotations=RO)
    async def get_job(
        reference_number: Annotated[str, Field(description="Referenznummer of the offer, e.g. '10001-1000911926-S'")],
    ) -> dict[str, Any]:
        """Full job ad from the Jobbörse: description, locations, employer, contract details, link."""
        try:
            job = await ba().job_details(reference_number)
        except BAError as e:
            raise _err(e) from e
        if job is None:
            raise ToolError(f"No job with reference number {reference_number} (it may have been taken offline)")
        return job

    @mcp.tool(annotations=RO)
    async def search_courses(
        keyword: Annotated[str, Field(description="Topic, e.g. 'Python', 'Staplerschein', 'Umschulung Pflege'")],
        location: Annotated[str | None, Field(description="Town or postcode to search around")] = None,
        radius_km: Annotated[Literal[10, 25, 50, 100, 150, 200] | None, Field(description="Radius around location")] = None,
        state: Annotated[str | None, Field(description="Region code instead of location: BAW, BAY, BER, BRA, BRE, HAM, HES, "
                                                       "MBV, NDS, NRW, RPF, SAA, SAC, SAN, SLH, THÜ")] = None,
        remote_only: Annotated[bool, Field(description="Only location-independent (online) courses")] = False,
        page: Annotated[int, Field(ge=0)] = 0,
        size: Annotated[int, Field(ge=1, le=50)] = 20,
    ) -> dict[str, Any]:
        """Search further-training courses (Weiterbildungssuche of mein NOW / KURSNET).

        Results list course offers with up to five dates each; pass a date id to get_course for
        details such as funding (Bildungsgutschein), costs, contacts and requirements.
        """
        try:
            return await ba().search_courses(keyword, location, radius_km=radius_km, state=state,
                                             remote_only=remote_only, page=page, size=size)
        except (BAError, ValueError) as e:
            raise _err(e) from e

    @mcp.tool(annotations=RO)
    async def get_course(
        date_id: Annotated[str, Field(description="Course date id from search_courses, e.g. '413425273_16891145_311625_kursnet'")],
    ) -> dict[str, Any]:
        """Details of one course date: content, requirements, certificate, cost, funding options, provider contact."""
        try:
            course = await ba().course_details(date_id)
        except BAError as e:
            raise _err(e) from e
        if course is None:
            raise ToolError(f"No course date {date_id}")
        return course

    @mcp.tool(annotations=RO)
    async def search_professions(
        query: Annotated[str, Field(description="Occupation name, e.g. 'Fachinformatiker', 'Erzieher'")],
        size: Annotated[int, Field(ge=1, le=50)] = 20,
    ) -> dict[str, Any]:
        """Find occupations in BERUFENET; returns profession ids for get_profession."""
        try:
            return await ba().search_professions(query, size)
        except BAError as e:
            raise _err(e) from e

    @mcp.tool(annotations=RO)
    async def get_profession(
        profession_id: Annotated[int, Field(description="BERUFENET id from search_professions")],
        sections: Annotated[list[str] | None, Field(
            description="Section titles (or parts of them) to include, e.g. ['Verdienst', 'Zugang', 'Kompetenzen']. "
                        "Default: overview, tasks, access, working conditions, pay, further training, alternatives")] = None,
    ) -> dict[str, Any]:
        """BERUFENET occupation profile: tasks, access requirements, pay, training, alternatives.

        Also returns `salary_kldb_code` for get_salaries.
        """
        try:
            prof = await ba().profession(profession_id, sections)
        except BAError as e:
            raise _err(e) from e
        if prof is None:
            raise ToolError(f"No profession with id {profession_id}")
        return prof

    @mcp.tool(annotations=RO)
    async def get_salaries(
        kldb: Annotated[str, Field(description="KldB 2010 code (3-5 digits), e.g. '43412' or 'B 43412'; "
                                               "get it from get_profession")],
        region: Annotated[str | None, Field(description="'Deutschland' (default), 'Ostdeutschland', 'Westdeutschland', "
                                                        "a Bundesland or a big city like 'Leipzig'")] = None,
        level: Annotated[Literal["helfer", "fachkraft", "spezialist", "experte"] | None,
                         Field(description="Requirement level (only for 3-4 digit codes)")] = None,
        gender: Literal["gesamt", "maenner", "frauen"] | None = None,
        age: Literal["gesamt", "unter_25", "25_bis_55", "ab_55"] | None = None,
        industry: Annotated[str | None, Field(description="Industry filter, e.g. 'information_kommunikation', "
                                                          "'oeffentlicher_dienst_bildung_gesundheit_soziales'")] = None,
    ) -> dict[str, Any]:
        """Gross monthly salaries from the BA Entgeltatlas (median and quartiles of full-time employees).

        Useful for judging whether a job offer is reasonable (Zumutbarkeit) and for salary expectations.
        """
        try:
            return await ba().salaries(kldb, region=region, level=level, gender=gender, age=age, industry=industry)
        except (BAError, ValueError) as e:
            raise _err(e) from e

    @mcp.tool(annotations=RO)
    async def find_offices(
        query: Annotated[str, Field(description="Postcode, town or office name")],
        kinds: Annotated[list[Literal["Arbeitsagenturen", "Jobcenter", "Familienkassen", "Berufsinformationszentren"]] | None,
                         Field(description="Restrict to these office types")] = None,
    ) -> dict[str, Any]:
        """Find the Agentur für Arbeit, Jobcenter or Familienkasse responsible for an address, with address and web page."""
        try:
            res = await ba().search_offices(query)
        except BAError as e:
            raise _err(e) from e
        if kinds:
            res["offices"] = [o for o in res["offices"] if o.get("kind") in kinds]
        return res

    # ---------------------------------------------------------------------------------------
    # Case file: profile and overview
    # ---------------------------------------------------------------------------------------

    @mcp.tool(annotations=LOCAL_RO)
    def overview(
        horizon_days: Annotated[int, Field(ge=1, le=120, description="Look-ahead for appointments")] = 14,
    ) -> dict[str, Any]:
        """Dashboard of the case file: alerts, upcoming appointments, open deadlines (Widerspruch,
        tasks, Vermittlungsvorschläge), application count against the monthly requirement."""
        return db().overview(horizon_days=horizon_days)

    @mcp.tool(annotations=LOCAL_RO)
    def get_profile() -> dict[str, Any]:
        """The customer's stored profile plus the list of fields that can be set."""
        return {"profile": db().profile(), "fields": PROFILE_FIELDS}

    @mcp.tool(annotations=LOCAL_RW)
    def update_profile(
        fields: Annotated[dict[str, str], Field(description="Profile fields to set, e.g. {'customer_number': '123A456789', "
                                                            "'benefit': 'alg', 'state': 'SN'}; empty string deletes a field. "
                                                            "See get_profile for all fields.")],
    ) -> dict[str, str]:
        """Set or change profile fields (name, address, Kundennummer, benefit type, Bundesland, dates, counselor ...)."""
        try:
            if "state" in fields and fields["state"]:
                fields = {**fields, "state": deadlines.normalize_state(fields["state"])}
            if fields.get("benefit") and fields["benefit"] not in {"alg", "grundsicherung", "keine"}:
                raise ValueError("benefit must be 'alg', 'grundsicherung' or 'keine'")
            return db().update_profile(fields)
        except ValueError as e:
            raise _err(e) from e

    # ---------------------------------------------------------------------------------------
    # Applications (Eigenbemühungen)
    # ---------------------------------------------------------------------------------------

    @mcp.tool(annotations=LOCAL_RW)
    async def add_application(
        employer: Annotated[str | None, Field(description="Employer name (filled from the job ad if reference_number is given)")] = None,
        position: Annotated[str | None, Field(description="Job title (filled from the job ad if reference_number is given)")] = None,
        applied_on: Annotated[str | None, Field(description="Date of the application; omit for a planned one")] = None,
        source: Annotated[Literal[tuple(APPLICATION_SOURCES)], Field(  # type: ignore[valid-type]
            description="How the job was found; 'vermittlungsvorschlag' = job proposal from the agency (must apply and report back)")] = "eigeninitiative",
        channel: Literal[tuple(APPLICATION_CHANNELS)] | None = None,  # type: ignore[valid-type]
        status: Annotated[Literal[tuple(APPLICATION_STATUSES)] | None, Field(  # type: ignore[valid-type]
            description="Default: 'beworben' if applied_on is given, else 'geplant'")] = None,
        reference_number: Annotated[str | None, Field(description="Jobbörse Referenznummer; employer/position/address are looked up")] = None,
        employer_address: str | None = None,
        job_url: str | None = None,
        contact_person: str | None = None,
        proposal_received_on: Annotated[str | None, Field(description="For Vermittlungsvorschläge: date received")] = None,
        apply_by: Annotated[str | None, Field(description="Deadline to apply (Vermittlungsvorschlag: see the letter; default received + 3 days)")] = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Record an application (Bewerbung) or a received Vermittlungsvorschlag in the case file."""
        looked_up = None
        if reference_number and not (employer and position and employer_address):
            try:
                looked_up = await ba().job_details(reference_number)
            except BAError:
                looked_up = None
            if looked_up:
                employer = employer or looked_up.get("employer")
                position = position or looked_up.get("title")
                job_url = job_url or looked_up.get("external_url") or looked_up.get("url")
                if not employer_address and looked_up.get("addresses"):
                    a = looked_up["addresses"][0]
                    street = " ".join(x for x in (a.get("strasse"), a.get("hausnummer")) if x)
                    employer_address = ", ".join(x for x in (street, " ".join(y for y in (a.get("plz"), a.get("ort")) if y)) if x) or None
        if not employer or not position:
            raise ToolError("employer and position are required (or a valid reference_number)")
        try:
            row = db().add_application(employer=employer, position=position, applied_on=applied_on, source=source,
                                       channel=channel, status=status, employer_address=employer_address,
                                       reference_number=reference_number, job_url=job_url, contact_person=contact_person,
                                       proposal_received_on=proposal_received_on, apply_by=apply_by, notes=notes)
        except ValueError as e:
            raise _err(e) from e
        hints = []
        if row["source"] == "vermittlungsvorschlag":
            hints.append("Vermittlungsvorschlag: bewerben bis apply_by (Frist im Schreiben prüfen) und das Ergebnis "
                         "zurückmelden (update_application result_reported_on, Brief: draft_letter "
                         "kind='rueckmeldung_vermittlungsvorschlag'). Ablehnung ohne wichtigen Grund -> Sperrzeit.")
        return {"application": row, "hints": hints}

    @mcp.tool(annotations=LOCAL_RW)
    def update_application(
        application_id: int,
        status: Literal[tuple(APPLICATION_STATUSES)] | None = None,  # type: ignore[valid-type]
        status_date: Annotated[str | None, Field(description="When the status changed (default today)")] = None,
        applied_on: str | None = None,
        channel: Literal[tuple(APPLICATION_CHANNELS)] | None = None,  # type: ignore[valid-type]
        result_reported_on: Annotated[str | None, Field(description="Date the result was reported to the agency")] = None,
        contact_person: str | None = None,
        employer_address: str | None = None,
        apply_by: str | None = None,
        notes: Annotated[str | None, Field(description="Replaces the notes")] = None,
    ) -> dict[str, Any]:
        """Update an application: new status (Eingangsbestätigung, Vorstellungsgespräch, Zusage, Absage ...), dates, notes."""
        try:
            return db().update_application(application_id, status=status, status_date=status_date, applied_on=applied_on,
                                           channel=channel, result_reported_on=result_reported_on,
                                           contact_person=contact_person, employer_address=employer_address,
                                           apply_by=apply_by, notes=notes)
        except (KeyError, ValueError) as e:
            raise _err(e) from e

    @mcp.tool(annotations=LOCAL_RO)
    def list_applications(
        status: Literal[tuple(APPLICATION_STATUSES)] | None = None,  # type: ignore[valid-type]
        source: Literal[tuple(APPLICATION_SOURCES)] | None = None,  # type: ignore[valid-type]
        since: str | None = None,
        until: str | None = None,
        limit: Annotated[int, Field(ge=1, le=1000)] = 200,
    ) -> dict[str, Any]:
        """List recorded applications, newest first, optionally filtered."""
        try:
            rows = db().list_applications(status=status, source=source, since=since, until=until, limit=limit)
        except ValueError as e:
            raise _err(e) from e
        return {"count": len(rows), "applications": rows}

    @mcp.tool(annotations=LOCAL_RW)
    def proof_of_applications(
        since: Annotated[str, Field(description="First day, e.g. '2026-10-01'")],
        until: Annotated[str, Field(description="Last day, e.g. '2026-10-31'")],
        format: Literal["markdown", "csv"] = "markdown",
        output_path: Annotated[str | None, Field(description="Optional file path to write the document to")] = None,
    ) -> str:
        """Generate the 'Nachweis der Eigenbemühungen' (list of applications) for a period, to hand
        in or upload in the eServices. Returns the document; optionally also writes it to a file."""
        try:
            doc = db().proof_of_applications(since, until, format)
        except ValueError as e:
            raise _err(e) from e
        if output_path:
            p = Path(output_path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(doc, encoding="utf-8")
            doc += f"\n(Gespeichert unter {p})\n"
        return doc

    # ---------------------------------------------------------------------------------------
    # Appointments
    # ---------------------------------------------------------------------------------------

    @mcp.tool(annotations=LOCAL_RW)
    def add_appointment(
        starts_at: Annotated[str, Field(description="Date and time, e.g. '2026-10-20T09:30' or '20.10.2026 09:30'")],
        kind: Literal[tuple(APPOINTMENT_KINDS)],  # type: ignore[valid-type]
        location: Annotated[str | None, Field(description="Address / room, or 'Telefon' / 'Video'")] = None,
        with_whom: str | None = None,
        purpose: Annotated[str | None, Field(description="Purpose stated in the invitation")] = None,
        invitation_date: str | None = None,
        bring: Annotated[str | None, Field(description="Documents to bring")] = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Record an appointment (Meldetermin, Beratung, ärztlicher Dienst, Maßnahme, Vorstellungsgespräch).

        Missing an invitation from the agency without a good reason has consequences (rules topic 'termine').
        """
        try:
            row = db().add_appointment(starts_at=starts_at, kind=kind, location=location, with_whom=with_whom,
                                       purpose=purpose, invitation_date=invitation_date, bring=bring, notes=notes)
        except ValueError as e:
            raise _err(e) from e
        hint = None
        if row["kind"] in {"meldetermin", "beratung", "aerztlicher_dienst", "psychologischer_dienst"}:
            hint = ("Pflichttermin: Bei Verhinderung VORHER absagen und Grund belegen (draft_letter kind='terminabsage'); "
                    "Versäumnis ohne wichtigen Grund -> Sperrzeit 1 Woche bzw. Leistungsminderung.")
        return {"appointment": row, "hint": hint}

    @mcp.tool(annotations=LOCAL_RW)
    def update_appointment(
        appointment_id: int,
        status: Literal[tuple(APPOINTMENT_STATUSES)] | None = None,  # type: ignore[valid-type]
        starts_at: Annotated[str | None, Field(description="New date/time if rescheduled")] = None,
        location: str | None = None,
        with_whom: str | None = None,
        purpose: str | None = None,
        bring: str | None = None,
        notes: Annotated[str | None, Field(description="Replaces the notes, e.g. outcome of the meeting")] = None,
    ) -> dict[str, Any]:
        """Update an appointment: mark as attended (wahrgenommen), cancelled, rescheduled or missed; add outcome notes."""
        try:
            return db().update_appointment(appointment_id, status=status, starts_at=starts_at, location=location,
                                           with_whom=with_whom, purpose=purpose, bring=bring, notes=notes)
        except (KeyError, ValueError) as e:
            raise _err(e) from e

    @mcp.tool(annotations=LOCAL_RO)
    def list_appointments(
        upcoming_only: Annotated[bool, Field(description="false lists all appointments, newest first")] = True,
    ) -> dict[str, Any]:
        """List appointments (default: upcoming planned ones)."""
        rows = db().list_appointments(upcoming_only=upcoming_only)
        return {"count": len(rows), "appointments": rows}

    # ---------------------------------------------------------------------------------------
    # Correspondence
    # ---------------------------------------------------------------------------------------

    @mcp.tool(annotations=LOCAL_RW)
    def log_correspondence(
        date: Annotated[str, Field(description="Date of the letter (as printed on it) or of the call/visit")],
        kind: Annotated[Literal[tuple(CORRESPONDENCE_KINDS)], Field(  # type: ignore[valid-type]
            description="'bescheid' = formal decision (gets a Widerspruch deadline), 'anhoerung' = hearing before a sanction")],
        subject: Annotated[str, Field(description="What it is about, e.g. 'Bewilligung Arbeitslosengeld' or 'Sperrzeit 1 Woche'")],
        direction: Literal["eingang", "ausgang"] = "eingang",
        channel: Literal[tuple(CHANNELS)] | None = None,  # type: ignore[valid-type]
        counterpart: Annotated[str | None, Field(description="Office / person")] = None,
        reference: Annotated[str | None, Field(description="Aktenzeichen / Zeichen")] = None,
        summary: str | None = None,
        received_on: Annotated[str | None, Field(description="Actual day of receipt if later than usual (keep the envelope)")] = None,
        legal_remedy_instruction_ok: Annotated[bool, Field(description="false if the Bescheid has no or a wrong Rechtsbehelfsbelehrung")] = True,
        reply_by: Annotated[str | None, Field(description="Deadline stated in the letter (Anhörung, Aufforderung); creates a task")] = None,
        file_path: Annotated[str | None, Field(description="Path to a scan/PDF of the document")] = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Record a letter, decision, e-mail, call or meeting with the agency / Jobcenter.

        For an incoming Bescheid the Widerspruch deadline is calculated and tracked automatically.
        """
        st = user_state(None)
        values: dict[str, Any] = {"date": date, "kind": kind, "subject": subject, "direction": direction,
                                  "channel": channel, "counterpart": counterpart, "reference": reference,
                                  "summary": summary, "received_on": received_on, "file_path": file_path, "notes": notes}
        calc = None
        try:
            if kind == "bescheid" and direction == "eingang":
                delivery = "personal" if channel == "persoenlich" else "electronic" if channel == "eservice" else "post"
                calc = deadlines.objection_deadline(parse_date(date, "date"), received=parse_date(received_on, "received_on"),
                                                    delivery=delivery, state=st,
                                                    legal_remedy_instruction_ok=legal_remedy_instruction_ok)
                values["objection_deadline"] = calc.deadline.isoformat()
                values["objection_status"] = "offen"
            row = db().add_correspondence(**values)
            task = None
            if reply_by:
                task = db().add_task(title=f"Antworten auf: {subject}", due=reply_by, source=kind,
                                     related=f"correspondence #{row['id']}")
        except ValueError as e:
            raise _err(e) from e
        out: dict[str, Any] = {"entry": row}
        if calc:
            out["objection_deadline"] = calc.as_dict()
        if task:
            out["task"] = task
        if kind == "anhoerung":
            out["hint"] = ("Anhörung: fristgerecht schriftlich antworten und den wichtigen Grund mit Belegen darlegen; "
                           "sonst wird nach Aktenlage entschieden (rules topic 'sperrzeit').")
        return out

    @mcp.tool(annotations=LOCAL_RW)
    def update_correspondence(
        entry_id: int,
        objection_status: Annotated[Literal["offen", "eingelegt", "verzichtet", "erledigt"] | None,
                                    Field(description="Track the Widerspruch for a Bescheid")] = None,
        subject: str | None = None,
        reference: str | None = None,
        summary: str | None = None,
        file_path: str | None = None,
        notes: Annotated[str | None, Field(description="Replaces the notes")] = None,
    ) -> dict[str, Any]:
        """Update a correspondence entry, e.g. mark that a Widerspruch has been filed."""
        try:
            return db().update_correspondence(entry_id, objection_status=objection_status, subject=subject,
                                              reference=reference, summary=summary, file_path=file_path, notes=notes)
        except (KeyError, ValueError) as e:
            raise _err(e) from e

    @mcp.tool(annotations=LOCAL_RO)
    def list_correspondence(
        kind: Literal[tuple(CORRESPONDENCE_KINDS)] | None = None,  # type: ignore[valid-type]
        since: str | None = None,
        query: Annotated[str | None, Field(description="Full-text filter on subject, summary, reference, notes")] = None,
        limit: Annotated[int, Field(ge=1, le=1000)] = 100,
    ) -> dict[str, Any]:
        """List recorded correspondence, newest first."""
        try:
            rows = db().list_correspondence(kind=kind, since=since, query=query, limit=limit)
        except ValueError as e:
            raise _err(e) from e
        return {"count": len(rows), "correspondence": rows}

    # ---------------------------------------------------------------------------------------
    # Tasks
    # ---------------------------------------------------------------------------------------

    @mcp.tool(annotations=LOCAL_RW)
    def add_task(
        title: Annotated[str, Field(description="What to do, e.g. 'Lebenslauf an Vermittlerin schicken'")],
        due: str | None = None,
        source: Annotated[str | None, Field(description="Where the duty comes from, e.g. 'Kooperationsplan vom 01.10.2026'")] = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Add a to-do / obligation (e.g. from the Eingliederungsvereinbarung / Kooperationsplan)."""
        try:
            return db().add_task(title=title, due=due, source=source, notes=notes)
        except ValueError as e:
            raise _err(e) from e

    @mcp.tool(annotations=LOCAL_RW)
    def complete_task(task_id: int, done_on: str | None = None, notes: str | None = None) -> dict[str, Any]:
        """Mark a task as done (default today)."""
        try:
            return db().complete_task(task_id, done_on, notes)
        except (KeyError, ValueError) as e:
            raise _err(e) from e

    @mcp.tool(annotations=LOCAL_RO)
    def list_tasks(include_done: bool = False) -> dict[str, Any]:
        """List open tasks ordered by due date (optionally including completed ones)."""
        rows = db().list_tasks(include_done=include_done)
        return {"count": len(rows), "tasks": rows}

    @mcp.tool(annotations=LOCAL_DEL)
    def delete_entry(
        kind: Literal["application", "appointment", "correspondence", "task"],
        entry_id: int,
    ) -> dict[str, Any]:
        """Permanently delete one entry from the case file (e.g. a duplicate). Returns the deleted entry."""
        try:
            return {"deleted": db().delete(kind, entry_id)}
        except (KeyError, ValueError) as e:
            raise _err(e) from e

    # ---------------------------------------------------------------------------------------
    # Deadlines and rules
    # ---------------------------------------------------------------------------------------

    @mcp.tool(annotations=LOCAL_RO)
    def registration_deadlines(
        employment_end: Annotated[str | None, Field(description="Last day of employment; default from profile")] = None,
        learned_on: Annotated[str | None, Field(description="Day the end became known (notice received); default from profile or today")] = None,
    ) -> dict[str, Any]:
        """Deadlines to register as job-seeking (§ 38 SGB III) and as unemployed (§ 141 SGB III)."""
        profile = db().profile()
        try:
            end = parse_date(employment_end or profile.get("employment_end"), "employment_end")
            if end is None:
                raise ValueError("employment_end is required (or set it in the profile)")
            known = parse_date(learned_on or profile.get("termination_known_on"), "learned_on") or min(date.today(), end)
            js = deadlines.job_seeker_registration(end, known)
            un = deadlines.unemployment_registration(end)
        except ValueError as e:
            raise _err(e) from e
        return {
            "arbeitsuchend_melden": js.as_dict(),
            "arbeitslos_melden": un.as_dict(),
            "already_done": {k: profile[k] for k in ("registered_job_seeking_on", "registered_unemployed_on") if k in profile},
        }

    @mcp.tool(annotations=LOCAL_RO)
    def objection_deadline(
        letter_date: Annotated[str, Field(description="Date of the Bescheid / day it was posted")],
        received_on: Annotated[str | None, Field(description="Actual day of receipt, if later than the 4th day")] = None,
        delivery: Literal["post", "electronic", "personal"] = "post",
        state: Annotated[str | None, Field(description="Bundesland of the issuing office for holidays; default from profile")] = None,
        legal_remedy_instruction_ok: bool = True,
    ) -> dict[str, Any]:
        """Last day to file a Widerspruch against a Bescheid (§ 84 SGG, § 37 SGB X), with step-by-step reasoning."""
        try:
            d = deadlines.objection_deadline(parse_date(letter_date, "letter_date"),
                                             received=parse_date(received_on, "received_on"), delivery=delivery,
                                             state=user_state(state), legal_remedy_instruction_ok=legal_remedy_instruction_ok)
        except ValueError as e:
            raise _err(e) from e
        out = d.as_dict()
        out["days_left"] = (d.deadline - date.today()).days
        return out

    @mcp.tool(annotations=LOCAL_RO)
    def calculate_deadline(
        start: Annotated[str, Field(description="Day of the triggering event (not counted)")],
        months: Annotated[int, Field(ge=0)] = 0,
        weeks: Annotated[int, Field(ge=0)] = 0,
        days: Annotated[int, Field(ge=0)] = 0,
        state: Annotated[str | None, Field(description="Bundesland for holidays; default from profile")] = None,
    ) -> dict[str, Any]:
        """Generic period calculation under § 26 SGB X / § 64 SGG (end moves off weekends and holidays),
        e.g. a 2-week deadline in a letter from the agency."""
        try:
            d = deadlines.period_end(parse_date(start, "start"), months=months, weeks=weeks, days=days, state=user_state(state))
        except ValueError as e:
            raise _err(e) from e
        out = d.as_dict()
        out["days_left"] = (d.deadline - date.today()).days
        return out

    @mcp.tool(annotations=LOCAL_RO)
    def unemployment_benefit_duration(
        months_insured_last_5_years: Annotated[int, Field(ge=0, le=60, description="Months of compulsory insurance (employment) in the last 5 years")],
        age: Annotated[int, Field(ge=14, le=80, description="Age when the claim arises")],
        months_insured_last_30_months: Annotated[int | None, Field(ge=0, le=30, description="Months insured within the 30-month Rahmenfrist")] = None,
    ) -> dict[str, Any]:
        """Estimate how long Arbeitslosengeld is paid (§ 147 SGB III)."""
        return deadlines.alg_entitlement_months(months_insured_last_5_years, age, months_insured_last_30_months)

    @mcp.tool(annotations=LOCAL_RO)
    def public_holidays(
        year: Annotated[int, Field(ge=1990, le=2100)],
        state: Annotated[str | None, Field(description="Bundesland; default from profile, else nationwide only")] = None,
    ) -> dict[str, Any]:
        """Public holidays relevant for deadline calculations."""
        try:
            st = user_state(state)
        except ValueError as e:
            raise _err(e) from e
        hols = deadlines.public_holidays(year, st)
        return {"state": st or "bundesweit", "holidays": {d.isoformat(): n for d, n in sorted(hols.items())}}

    @mcp.tool(annotations=LOCAL_RO)
    def rules(
        topic: Annotated[Literal[tuple(guide.TOPICS)], Field(  # type: ignore[valid-type]
            description="One of: " + guide.topic_list())],
    ) -> str:
        """Plain-language summary of the customer's rights and duties on a topic, with legal references."""
        return guide.TOPICS[topic] + "\n\n(Allgemeine Information, keine Rechtsberatung. Stand 2026.)"

    # ---------------------------------------------------------------------------------------
    # Letters
    # ---------------------------------------------------------------------------------------

    @mcp.tool(annotations=LOCAL_RW)
    def draft_letter(
        kind: Annotated[Literal[tuple(letters.LETTERS)], Field(  # type: ignore[valid-type]
            description="; ".join(f"{k}: {v[1]}" for k, v in letters.LETTERS.items()))],
        params: Annotated[dict[str, Any], Field(description="Letter parameters (see kind). Common optional ones: "
                                                            "recipient, reference, date, place, attachments (list)")],
        log: Annotated[bool, Field(description="Also record the letter as outgoing correspondence")] = False,
    ) -> str:
        """Draft a letter to the Agentur für Arbeit / Jobcenter using the profile (sender, Kundennummer,
        responsible office). The user must check, sign and send it; nothing is sent from here."""
        try:
            letter = letters.render(kind, db().profile(), params)
            if log:
                db().add_correspondence(date=params.get("date") or date.today().isoformat(), direction="ausgang",
                                        kind="widerspruch" if kind == "widerspruch" else "antrag" if kind in {
                                            "bildungsgutschein", "ueberpruefungsantrag", "akteneinsicht", "ortsabwesenheit"} else "brief",
                                        subject=letter.subject,
                                        reference=params.get("reference"), summary=f"Entwurf erstellt ({kind})",
                                        notes="Entwurf - Versanddatum und Versandweg nachtragen")
        except (KeyError, ValueError) as e:
            raise _err(e) from e
        return letter.text

    # ---------------------------------------------------------------------------------------
    # Meine BA (the user's own account, user-performed login)
    # ---------------------------------------------------------------------------------------

    @mcp.tool(annotations=LOCAL_RO)
    def meineba_status() -> dict[str, Any]:
        """Which Meine BA services are logged in, how long the sessions last, and what each one offers."""
        return mba().status()

    @mcp.tool(annotations=LOCAL_RW)
    def meineba_login_start(
        service: Annotated[Literal[tuple(SERVICES)], Field(  # type: ignore[valid-type]
            description="; ".join(f"{k}: {v.description}" for k, v in SERVICES.items()))],
    ) -> dict[str, Any]:
        """Start a login to the user's Meine BA account for one service. Returns a link the USER opens in
        their own browser to sign in on sso.arbeitsagentur.de; never ask for or handle their password."""
        try:
            return mba().login_start(service)
        except MeineBAError as e:
            raise _err(e) from e

    @mcp.tool(annotations=LOCAL_RW)
    async def meineba_login_finish(
        redirect_url: Annotated[str, Field(description="The full address the browser showed after signing in "
                                                       "(contains code= and state=)")],
    ) -> dict[str, Any]:
        """Complete a login started with meineba_login_start by exchanging the one-time code."""
        try:
            return await mba().login_finish(redirect_url)
        except MeineBAError as e:
            raise _err(e) from e

    @mcp.tool(annotations=LOCAL_DEL)
    async def meineba_logout(
        service: Annotated[Literal[tuple(SERVICES)] | None, Field(description="Omit to log out of all")] = None,  # type: ignore[valid-type]
    ) -> dict[str, Any]:
        """End Meine BA sessions and delete the stored tokens."""
        return await mba().logout(service)

    async def _call(coro):
        try:
            return await coro
        except MeineBAError as e:
            raise _err(e) from e

    @mcp.tool(annotations=RO)
    async def meineba_postfach(
        folder: Literal[tuple(POSTFACH_FOLDERS)] = "erhalten",  # type: ignore[valid-type]
    ) -> Any:
        """List messages in the user's BA Postfach (erhalten = inbox, gesendet, entwurf, geloescht)."""
        return await _call(mba().postfach_list(folder))

    @mcp.tool(annotations=RO)
    async def meineba_postfach_read(
        message_id: str,
        folder: Literal[tuple(POSTFACH_FOLDERS)] = "erhalten",  # type: ignore[valid-type]
    ) -> Any:
        """Read one Postfach message including its history and attachment list. Opening a message may mark it as read."""
        return await _call(mba().postfach_read(folder, message_id))

    @mcp.tool(annotations=LOCAL_RW)
    async def meineba_postfach_attachment(
        message_id: str,
        attachment_id: str,
        save_to: Annotated[str, Field(description="File path to save the attachment to")],
        folder: Literal[tuple(POSTFACH_FOLDERS)] = "erhalten",  # type: ignore[valid-type]
    ) -> dict[str, Any]:
        """Download an attachment of a Postfach message (e.g. a Bescheid as PDF) to a local file (mode 0600)."""
        return await _call(mba().postfach_attachment(folder, message_id, attachment_id, Path(save_to).expanduser()))

    @mcp.tool(annotations=RO)
    async def meineba_postfach_recipients() -> dict[str, Any]:
        """Offices the user can write to via the Postfach (Agentur = AA, Jobcenter = JC, ...) and the topics
        ('bezug') each accepts. Needed before meineba_postfach_send."""
        return await _call(mba().postfach_recipients())

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=False))
    async def meineba_postfach_send(
        recipient_id: Annotated[str, Field(description="dienststellenNummer from meineba_postfach_recipients")],
        recipient_name: Annotated[str, Field(description="dienststellenName from meineba_postfach_recipients")],
        topic: Annotated[str, Field(description="'bezug' of the chosen topic/subtopic from meineba_postfach_recipients")],
        subject: str,
        text: str,
        confirm: Annotated[bool, Field(description="Must be true to actually send. Only set it after the user "
                                                   "has seen and approved this exact message.")] = False,
    ) -> dict[str, Any]:
        """Send a message to the Agentur für Arbeit / Jobcenter through the user's Postfach.

        Without confirm=true this only returns a preview. Sent messages are binding communication with the
        authority and are recorded in the local case file.
        """
        preview = {"to": f"{recipient_name} ({recipient_id})", "topic": topic, "subject": subject, "text": text}
        if not confirm:
            return {"sent": False, "preview": preview,
                    "next": "Show this to the user. Call again with confirm=true only after they approve it."}
        res = await _call(mba().postfach_send(recipient_id=recipient_id, recipient_name=recipient_name,
                                              topic=topic, subject=subject, text=text))
        entry = db().add_correspondence(date=date.today().isoformat(), direction="ausgang", kind="nachricht",
                                        channel="eservice", counterpart=recipient_name, subject=subject,
                                        summary=text[:500], notes=f"Über Meine BA Postfach gesendet (Bezug: {topic})")
        return {"sent": True, "response": res, "logged_as": entry["id"]}

    @mcp.tool(annotations=RO)
    async def meineba_termine(
        now: Annotated[str | None, Field(description="Reference date YYYY-MM-DD (default today)")] = None,
    ) -> Any:
        """Appointments booked with the Agentur für Arbeit / Jobcenter (Termine in Meine BA)."""
        return await _call(mba().appointments(now))

    @mcp.tool(annotations=RO)
    async def meineba_verlauf(
        limit: Annotated[int, Field(ge=1, le=200)] = 20,
        before: Annotated[str | None, Field(description="Entry id to page backwards from")] = None,
        search: str | None = None,
    ) -> Any:
        """History of events in the user's account (applications filed, letters, decisions, documents)."""
        return await _call(mba().history(limit, before, search))

    @mcp.tool(annotations=RO)
    async def meineba_verlauf_eintrag(entry_id: str) -> Any:
        """One entry of the Verlauf with details and document links."""
        return await _call(mba().history_entry(entry_id))

    @mcp.tool(annotations=RO)
    async def meineba_antraege(limit: Annotated[int, Field(ge=1, le=200)] = 50) -> Any:
        """Status of the user's applications (Antragsübersicht), e.g. Arbeitslosengeld: what is pending and
        whether action is expected from the user."""
        return await _call(mba().applications(limit))

    @mcp.tool(annotations=RO)
    async def meineba_antrag(
        vorgangs_id: str,
        aue_version: Annotated[int, Field(description="aueVersion from meineba_antraege")],
    ) -> Any:
        """Details of one application: status, required actions, documents."""
        return await _call(mba().application(vorgangs_id, aue_version))

    @mcp.tool(annotations=RO)
    async def meineba_leistungen() -> Any:
        """Granted benefits and payments as shown in Meine BA."""
        return await _call(mba().benefits())

    @mcp.tool(annotations=RO)
    async def meineba_merkliste() -> Any:
        """The user's job watch list in the BA Jobsuche, with notes and application status per job."""
        return await _call(mba().watchlist())

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=False))
    async def meineba_merkliste_setzen(
        reference_number: str,
        note: Annotated[str | None, Field(description="Note (Notiz) for this job")] = None,
        status: Literal[tuple(WATCHLIST_STATUSES)] | None = None,  # type: ignore[valid-type]
    ) -> Any:
        """Add a job to the Jobsuche watch list or update its note / application status (BEWORBEN, EINGELADEN,
        ZUSAGE, ABSAGE)."""
        return await _call(mba().watchlist_set(reference_number, note, status))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=True))
    async def meineba_merkliste_entfernen(reference_number: str) -> Any:
        """Remove a job from the Jobsuche watch list (its note and status are lost)."""
        return await _call(mba().watchlist_remove(reference_number))

    @mcp.tool(annotations=RO)
    async def meineba_gespeicherte_suchen() -> Any:
        """Saved job searches (Suchaufträge) with e-mail alerts."""
        return await _call(mba().saved_searches())

    # ---------------------------------------------------------------------------------------
    # Prompts
    # ---------------------------------------------------------------------------------------

    @mcp.prompt()
    def wochencheck() -> str:
        """Weekly review of the case: deadlines, appointments, applications."""
        return ("Mach einen Wochencheck meiner Akte bei der Arbeitsagentur: Rufe overview auf, erkläre jede "
                "Warnung und was ich bis wann tun muss, prüfe, ob mir für diesen Monat noch Bewerbungen fehlen, "
                "und schlage mit search_jobs passende neue Stellen zu meinen Zielberufen (Profil target_jobs) vor. "
                "Trage nichts ohne meine Bestätigung ein.")

    @mcp.prompt()
    def bescheid_pruefen(bescheid_text: str) -> str:
        """Check a Bescheid (decision letter) for deadlines and possible grounds for an objection."""
        return ("Hier ist der Text eines Bescheids der Agentur für Arbeit / des Jobcenters:\n\n"
                f"{bescheid_text}\n\n"
                "1. Fasse zusammen, was entschieden wurde (Leistung, Zeitraum, Höhe, Sperrzeit/Minderung, Rückforderung). "
                "2. Berechne mit objection_deadline die Widerspruchsfrist (Datum des Bescheids; prüfe, ob eine "
                "Rechtsbehelfsbelehrung enthalten ist). 3. Nenne Punkte, die ich prüfen sollte (Berechnungsgrundlagen, "
                "Zeiträume, Begründung) - ohne Rechtsberatung zu versprechen. 4. Biete an, den Bescheid mit "
                "log_correspondence einzutragen und bei Bedarf einen Widerspruch mit draft_letter zu entwerfen.")

    @mcp.prompt()
    def kuendigung_erhalten(employment_end: str, notice_received: str) -> str:
        """What to do after receiving a notice of termination."""
        return (f"Ich habe am {notice_received} eine Kündigung zum {employment_end} erhalten. Trage beide Daten in "
                "mein Profil ein (update_profile employment_end, termination_known_on), berechne mit "
                "registration_deadlines meine Meldefristen, erkläre mir die Schritte (rules 'meldepflichten' und "
                "'unterlagen') und lege Aufgaben mit Fälligkeit dafür an (add_task).")

    return mcp


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="arbeitsagentur-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", help="Path of the case file database (default: $ARBEITSAGENTUR_MCP_DB or "
                                     "~/.local/share/arbeitsagentur-mcp/akte.sqlite3)")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()
    if args.db:
        os.environ["ARBEITSAGENTUR_MCP_DB"] = args.db
    server = create_server()
    if args.transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=args.host, port=args.port)
