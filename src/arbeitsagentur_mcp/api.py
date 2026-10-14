"""Client for the public (login-free) REST APIs behind arbeitsagentur.de and mein-now.de.

These are the same endpoints the BA's own web apps use; they are not officially documented.
The API keys below are the public client IDs embedded in those web apps (see bundesAPI on
GitHub for community documentation). Responses are condensed to the fields a job seeker needs
so they fit comfortably into a model's context.
"""

from __future__ import annotations

import base64
import html
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from . import __version__

REST = "https://rest.arbeitsagentur.de"
JOBSUCHE = f"{REST}/jobboerse/jobsuche-service"
BERUFENET = f"{REST}/infosysbub/bnet/pc/v1"
ENTGELTATLAS = f"{REST}/infosysbub/entgeltatlas/pc/v1"
DVOSUCHE = f"{REST}/portal/dvosuche/pc/v1"
NOW_SUCHE = "https://rest.mein-now.de/now-prod/suche/pc/v1"

KEY_JOBSUCHE = "jobboerse-jobsuche"
KEY_BERUFENET = "infosysbub-berufenet"
KEY_ENTGELTATLAS = "infosysbub-ega"
KEY_DVOSUCHE = "portal_dvosuche"
KEY_NOW_SUCHE = "infosysbub-nowsuche"

JOB_URL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
BERUFENET_URL = "https://web.arbeitsagentur.de/berufenet/beruf/{id}"

OFFER_TYPES = {"arbeit": 1, "selbstaendigkeit": 2, "ausbildung": 4, "praktikum": 34}
WORKING_TIMES = {"vollzeit": "vz", "teilzeit": "tz", "schicht": "snw", "homeoffice": "ho", "minijob": "mj"}
PERFORMANCE_LEVELS = {"helfer": 1, "fachkraft": 2, "spezialist": 3, "experte": 4}
GENDERS = {"gesamt": 1, "maenner": 2, "frauen": 3}
AGE_GROUPS = {"gesamt": 1, "unter_25": 2, "25_bis_55": 3, "ab_55": 4}
INDUSTRIES = {
    "gesamt": 1,
    "land_forst_fischerei": 2,
    "produzierendes_gewerbe": 3,
    "bau": 4,
    "handel_verkehr_gastgewerbe": 5,
    "information_kommunikation": 6,
    "finanzen_versicherungen": 7,
    "immobilien": 8,
    "wirtschaftliche_dienstleistungen": 9,
    "oeffentlicher_dienst_bildung_gesundheit_soziales": 10,
    "sonstige_dienstleistungen": 11,
}


class BAError(RuntimeError):
    """An upstream API failed or returned something unexpected."""


def strip_html(text: str | None, limit: int | None = None) -> str | None:
    """Turn the BA's HTML snippets into readable plain text."""
    if text is None:
        return None
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>", "\n", text)
    t = re.sub(r"(?i)<li[^>]*>", "\n- ", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\xa0]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n\n", t).strip()
    if limit and len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0] + " …"
    return t


def _ms_date(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, UTC).date().isoformat()


def _drop_empty(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def encode_refnr(refnr: str) -> str:
    return base64.b64encode(refnr.strip().encode()).decode()


def kldb_code(value: str | int) -> str:
    """'B 91244' / 'B 91244-11300' / 91244 -> '91244'."""
    m = re.search(r"\d{3,5}", str(value))
    if not m:
        raise ValueError(f"Not a KldB 2010 code: {value!r}")
    return m.group(0)


class BAClient:
    def __init__(self, client: httpx.AsyncClient | None = None, timeout: float = 30.0):
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": f"arbeitsagentur-mcp/{__version__} (+https://git.freifick.net/slop/arbeitsagentur-mcp)"},
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, url: str, key: str, **kw: Any) -> Any:
        headers = {"X-API-Key": key, "Accept": "application/json"}
        try:
            r = await self._client.request(method, url, headers=headers, **kw)
        except httpx.HTTPError as e:
            raise BAError(f"Request to {url} failed: {e}") from e
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise BAError(f"{method} {r.url} returned HTTP {r.status_code}: {r.text[:300]}")
        if not r.content:
            return None
        return r.json()

    async def _get(self, url: str, key: str, params: dict[str, Any] | None = None) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        return await self._request("GET", url, key, params=params)

    # --- Jobbörse -------------------------------------------------------------------------

    async def search_jobs(
        self,
        what: str | None = None,
        where: str | None = None,
        *,
        radius_km: int | None = None,
        offer_type: str | None = None,
        working_time: list[str] | None = None,
        published_since_days: int | None = None,
        fixed_term: bool | None = None,
        temp_agencies: bool | None = None,
        private_agencies: bool | None = None,
        employer: str | None = None,
        page: int = 1,
        size: int = 25,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"was": what, "wo": where, "umkreis": radius_km, "page": page, "size": size,
                                  "arbeitgeber": employer, "veroeffentlichtseit": published_since_days}
        if offer_type:
            try:
                params["angebotsart"] = OFFER_TYPES[offer_type.lower()]
            except KeyError:
                raise ValueError(f"offer_type must be one of {', '.join(OFFER_TYPES)}") from None
        if working_time:
            try:
                params["arbeitszeit"] = ";".join(WORKING_TIMES[w.lower()] for w in working_time)
            except KeyError:
                raise ValueError(f"working_time entries must be from {', '.join(WORKING_TIMES)}") from None
        if fixed_term is not None:
            params["befristung"] = 1 if fixed_term else 2
        if temp_agencies is not None:
            params["zeitarbeit"] = str(temp_agencies).lower()
        if private_agencies is not None:
            params["pav"] = str(private_agencies).lower()
        data = await self._get(f"{JOBSUCHE}/pc/v6/jobs", KEY_JOBSUCHE, params) or {}
        jobs = [self._job_summary(j) for j in data.get("ergebnisliste") or []]
        where_out = data.get("woOutput") or {}
        return _drop_empty({
            "total": data.get("maxErgebnisse", 0),
            "page": data.get("page", page),
            "size": data.get("size", size),
            "location_interpreted_as": where_out.get("bereinigterOrt"),
            "jobs": jobs,
        })

    @staticmethod
    def _location(locs: list[dict] | None) -> str | None:
        out = []
        for loc in locs or []:
            a = loc.get("adresse") or {}
            out.append(" ".join(x for x in (a.get("plz"), a.get("ort")) if x))
        out = [o for o in out if o]
        return "; ".join(dict.fromkeys(out)) or None

    def _job_summary(self, j: dict[str, Any]) -> dict[str, Any]:
        refnr = j.get("referenznummer") or j.get("refnr")
        return _drop_empty({
            "reference_number": refnr,
            "title": j.get("stellenangebotsTitel") or j.get("titel"),
            "employer": j.get("firma") or j.get("arbeitgeber"),
            "occupation": j.get("hauptberuf") or j.get("beruf"),
            "location": self._location(j.get("stellenlokationen")),
            "distance_km": j.get("entfernung"),
            "offer_type": j.get("stellenangebotsart"),
            "full_time": j.get("arbeitszeitVollzeit"),
            "home_office": j.get("homeofficetyp") if j.get("homeofficemoeglich") else None,
            "start": (j.get("eintrittszeitraum") or {}).get("von"),
            "published": (j.get("veroeffentlichungszeitraum") or {}).get("von"),
            "external_url": j.get("externeUrl"),
            "url": JOB_URL.format(refnr=refnr) if refnr else None,
        })

    async def job_details(self, reference_number: str) -> dict[str, Any] | None:
        refnr = reference_number.strip()
        d = await self._get(f"{JOBSUCHE}/pc/v4/jobdetails/{encode_refnr(refnr)}", KEY_JOBSUCHE)
        if not d:
            return None
        out = self._job_summary(d)
        out.update(_drop_empty({
            "description": strip_html(d.get("stellenangebotsBeschreibung")),
            "pay": None if d.get("verguetungsangabe") in (None, "KEINE_ANGABEN") else d.get("verguetungsangabe"),
            "salary": d.get("verguetung") or d.get("gehalt"),
            "contract_duration": None if d.get("vertragsdauer") in (None, "KEINE_ANGABE") else d.get("vertragsdauer"),
            "first_published": d.get("datumErsteVeroeffentlichung"),
            "changed": d.get("aenderungsdatum"),
            "addresses": [
                _drop_empty({k: (loc.get("adresse") or {}).get(k) for k in ("strasse", "hausnummer", "plz", "ort", "land")})
                for loc in d.get("stellenlokationen") or []
            ],
            "temporary_agency": d.get("istZeitarbeit") or d.get("zeitarbeit"),
            "private_agency": d.get("istPrivateArbeitsvermittlung"),
            "handled_by_ba": d.get("istBetreut"),
            "partner_site": d.get("allianzpartnerName") if d.get("allianzpartnerName") != "arbeitsagentur.de" else None,
            "partner_url": d.get("allianzpartnerUrl") if d.get("allianzpartnerName") != "arbeitsagentur.de" else None,
            "contact": d.get("kontaktdaten") or d.get("arbeitgeberAdresse"),
            "how_to_apply": d.get("bewerbungsinformationen") or d.get("bewerbung"),
        }))
        return out

    # --- Weiterbildung (mein NOW / KURSNET) -----------------------------------------------

    async def geocode(self, place: str) -> dict[str, Any] | None:
        """Resolve a town name or postcode to name, PLZ and coordinates (mein NOW Ortsuche)."""
        res = await self._get(f"{NOW_SUCHE}/orte", KEY_NOW_SUCHE, {"suchwort": place})
        return res[0] if res else None

    async def search_courses(
        self,
        keyword: str,
        location: str | None = None,
        *,
        radius_km: int | None = None,
        state: str | None = None,
        remote_only: bool = False,
        page: int = 0,
        size: int = 20,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"sw": keyword, "page": page, "size": size}
        resolved = None
        if location:
            resolved = await self.geocode(location)
            if not resolved:
                raise ValueError(f"Could not resolve location {location!r}")
            name = resolved["name"].replace(",", ";")
            params["ort"] = f"{name}_{resolved.get('postleitzahl', '')}_{resolved['laengengrad']}_{resolved['breitengrad']}"
            params["uk"] = radius_km or 25
        if state:
            params["re"] = state
        if remote_only:
            params["ortsunabhaengig"] = "true"
        data = await self._get(f"{NOW_SUCHE}/bildungsangebot", KEY_NOW_SUCHE, params) or {}
        items = (data.get("_embedded") or {}).get("bildungsangebotDTOList") or []
        page_info = data.get("page") or {}
        return _drop_empty({
            "total": page_info.get("totalElements", 0),
            "page": page_info.get("number", page),
            "location_interpreted_as": resolved and f"{resolved.get('postleitzahl', '')} {resolved['name']}".strip(),
            "spelling_suggestion": data.get("korrekturVorschlag"),
            "courses": [self._course_summary(c) for c in items],
        })

    @staticmethod
    def _course_summary(c: dict[str, Any]) -> dict[str, Any]:
        anbieter = c.get("bildungsanbieter") or {}
        termine = c.get("termine") or []
        dates = []
        for t in termine[:5]:
            dates.append(_drop_empty({
                "id": t.get("id"),
                "start": _ms_date(t.get("beginn")),
                "end": _ms_date(t.get("ende")),
                "place": (t.get("adresse") or {}).get("ort"),
                "format": (t.get("unterrichtsform") or {}).get("bezeichnung"),
                "schedule": (t.get("unterrichtszeit") or {}).get("bezeichnung"),
                "cost": t.get("kostenWert"),
            }))
        return _drop_empty({
            "offer_id": c.get("id"),
            "title": c.get("titel"),
            "provider": anbieter.get("name"),
            "provider_location": " ".join(x for x in ((anbieter.get("adresse") or {}).get("plz"),
                                                      (anbieter.get("adresse") or {}).get("ort")) if x),
            "summary": strip_html(c.get("inhalt"), 300),
            "number_of_dates": c.get("anzahlTermine"),
            "dates": dates,
        })

    async def course_details(self, date_id: str) -> dict[str, Any] | None:
        """Details of one course date (Termin), id as returned in `dates[].id` of a search."""
        d = await self._get(f"{NOW_SUCHE}/bildungsangebot/{quote(date_id, safe='')}", KEY_NOW_SUCHE)
        if not d:
            return None
        a = d.get("angebot") or {}
        anbieter = a.get("bildungsanbieter") or {}
        funding = [f.get("bezeichnung") for f in (d.get("foerderartenBundesweit") or []) + (d.get("foerderartenBundesland") or [])]
        return _drop_empty({
            "date_id": d.get("id"),
            "offer_id": a.get("id"),
            "title": a.get("titel"),
            "type": (a.get("bildungsart") or {}).get("bezeichnung"),
            "content": strip_html(a.get("inhalt"), 4000),
            "target_group": strip_html(a.get("zielgruppe"), 1000),
            "requirements": strip_html(a.get("zugang"), 1000),
            "certificate": strip_html(a.get("abschlussbezeichnung")),
            "exam": strip_html(a.get("abschlussart")),
            "start": _ms_date(d.get("beginn")),
            "end": _ms_date(d.get("ende")),
            "duration": d.get("dauer"),
            "format": (d.get("unterrichtsform") or {}).get("bezeichnung"),
            "schedule": (d.get("unterrichtszeit") or {}).get("bezeichnung"),
            "part_time_compatible": d.get("berufsbegleitend"),
            "rolling_start": d.get("individuellerEinstieg"),
            "cost": d.get("kostenWert"),
            "cost_note": strip_html(d.get("kostenBemerkung")),
            "fundable": d.get("foerderung"),
            "funding_options": funding,
            "address": d.get("adresse"),
            "provider": _drop_empty({
                "name": anbieter.get("name"),
                "address": anbieter.get("adresse"),
                "phone": anbieter.get("telefon"),
                "email": anbieter.get("email"),
                "website": anbieter.get("homepage"),
            }),
            "contacts": [
                _drop_empty({"name": p.get("nachname"), "phone": p.get("telefonDurchwahl"), "email": p.get("email")})
                for p in d.get("ansprechpartner") or []
            ],
            "link": d.get("link"),
        })

    # --- BERUFENET ------------------------------------------------------------------------

    async def search_professions(self, query: str, size: int = 20) -> dict[str, Any]:
        data = await self._get(f"{BERUFENET}/berufe", KEY_BERUFENET, {"suchwoerter": query, "size": size, "page": 0}) or {}
        items = (data.get("_embedded") or {}).get("berufSucheList") or []
        return {
            "total": (data.get("page") or {}).get("totalElements", len(items)),
            "professions": [{"profession_id": b.get("id"), "name": b.get("kurzBezeichnungNeutral")} for b in items],
        }

    async def profession(self, profession_id: int, sections: list[str] | None = None) -> dict[str, Any] | None:
        data = await self._get(f"{BERUFENET}/berufe/{int(profession_id)}", KEY_BERUFENET)
        if not data:
            return None
        b = data[0] if isinstance(data, list) else data
        wanted = [s.lower() for s in sections] if sections else None
        default_ids = {"b10-0", "b11-0", "b30-0", "b50-0", "b16-0", "b40-01", "b60-1"}
        texts: dict[str, str] = {}
        available = []
        for f in b.get("infofelder") or []:
            title, fid = f.get("ueberschrift") or f.get("id"), f.get("id")
            if fid == "b02":  # pictures
                continue
            available.append(title)
            if (wanted is None and fid in default_ids) or (wanted and any(w in (title or "").lower() or w == fid for w in wanted)):
                texts[title] = strip_html(f.get("content"), 3000)
        return _drop_empty({
            "profession_id": b.get("id"),
            "name": b.get("bezeichnungNeutral"),
            "kldb2010": b.get("kldb2010"),
            "salary_kldb_code": kldb_code(b["kldb2010"]) if b.get("kldb2010") else None,
            "url": BERUFENET_URL.format(id=b.get("id")),
            "sections": texts,
            "other_sections_available": [a for a in available if a not in texts],
            "fields_of_activity": [t.get("kurzBezeichnungNeutral") for t in b.get("taetigkeitsfelder") or []],
            "further_training_adaptation": [t.get("kurzBezeichnungNeutral") for t in (b.get("anpassungsweiterbildungen") or [])[:15]],
            "further_training_advancement": [t.get("kurzBezeichnungNeutral") for t in (b.get("aufstiegsweiterbildungen") or [])[:15]],
        })

    # --- Entgeltatlas ---------------------------------------------------------------------

    async def salary_regions(self) -> list[dict[str, Any]]:
        return await self._get(f"{ENTGELTATLAS}/regionen", KEY_ENTGELTATLAS) or []

    async def salaries(
        self,
        kldb: str | int,
        *,
        region: str | None = None,
        level: str | None = None,
        gender: str | None = None,
        age: str | None = None,
        industry: str | None = None,
    ) -> dict[str, Any]:
        code = kldb_code(kldb)
        params: dict[str, Any] = {}
        region_name = "Deutschland"
        if region:
            regions = await self.salary_regions()
            match = next((r for r in regions if r.get("bezeichnung", "").lower() == region.lower()
                          or str(r.get("schluessel")).lower() == region.lower()), None)
            if not match:
                raise ValueError("Unknown region; use Deutschland, Ostdeutschland, Westdeutschland or a Bundesland: "
                                 + ", ".join(r["bezeichnung"] for r in regions))
            params["r"] = match["id"]
            region_name = match["bezeichnung"]
        if level:
            try:
                params["l"] = PERFORMANCE_LEVELS[level.lower()]
            except KeyError:
                raise ValueError(f"level must be one of {', '.join(PERFORMANCE_LEVELS)}") from None
        for name, value, table, param in (("gender", gender, GENDERS, "g"), ("age", age, AGE_GROUPS, "a"),
                                          ("industry", industry, INDUSTRIES, "b")):
            if value:
                try:
                    params[param] = table[value.lower()]
                except KeyError:
                    raise ValueError(f"{name} must be one of {', '.join(table)}") from None
        rows = await self._get(f"{ENTGELTATLAS}/entgelte/{code}", KEY_ENTGELTATLAS, params) or []
        out = []
        for r in rows:
            if (r.get("entgelt") or -1) < 0:
                continue
            if (r.get("branche") or {}).get("id") != params.get("b", 1):
                continue
            out.append(_drop_empty({
                "region": (r.get("region") or {}).get("bezeichnung"),
                "level": (r.get("performanceLevel") or {}).get("bezeichnung"),
                "gender": (r.get("gender") or {}).get("bezeichnung"),
                "age": (r.get("ageCategory") or {}).get("bezeichnung"),
                "industry": (r.get("branche") or {}).get("bezeichnung"),
                "median_gross_monthly_eur": r.get("entgelt"),
                "q25_eur": r.get("entgeltQ25"),
                "q75_eur": r.get("entgeltQ75"),
                "employees": r.get("besetzung"),
                "contribution_ceiling_eur": (r.get("region") or {}).get("beitragsBemessungsGrenze"),
            }))
        return {
            "kldb": code,
            "region": region_name,
            "note": "Bruttomonatsentgelte sozialversicherungspflichtig Vollzeitbeschäftigter (Median, 25%/75%-Quartil), "
                    "Statistik der BA. Werte an der Beitragsbemessungsgrenze sind gekappt.",
            "rows": out,
        }

    # --- Dienststellen --------------------------------------------------------------------

    async def search_offices(self, query: str, types: list[str] | None = None, start: int = 0) -> dict[str, Any]:
        body: dict[str, Any] = {"q": query, "startIndex": start}
        if types:
            body["dienststellenTypes"] = types
        data = await self._request("POST", f"{DVOSUCHE}/dvosearch", KEY_DVOSUCHE, json=body) or {}
        offices = []
        for o in data.get("data") or []:
            addr = o.get("visitingAddress") or {}
            offices.append(_drop_empty({
                "id": o.get("identifier"),
                "kind": o.get("dienststellenType"),
                "name": o.get("title"),
                "role": o.get("type"),
                "address": ", ".join(x for x in (addr.get("street"), " ".join(y for y in (addr.get("zipCode"), addr.get("city")) if y)) if x),
                "url": o.get("url"),
            }))
        extra = {k: v for k, v in data.items() if k != "data" and isinstance(v, (int, str))}
        return {"offices": offices, **extra}
