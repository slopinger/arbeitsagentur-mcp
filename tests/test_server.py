import json
from urllib.parse import parse_qs

import httpx
import pytest
from mcp import Client

from arbeitsagentur_mcp import api
from arbeitsagentur_mcp.server import create_server

JOB = {
    "stellenangebotsart": "ARBEIT", "stellenangebotsTitel": "Lagerist (m/w/d)", "arbeitszeitVollzeit": True,
    "eintrittszeitraum": {"von": "2026-11-01"}, "verguetungsangabe": "KEINE_ANGABEN",
    "stellenlokationen": [{"adresse": {"strasse": "Hauptstr.", "hausnummer": "1", "plz": "04109", "ort": "Leipzig"}}],
    "homeofficemoeglich": False, "veroeffentlichungszeitraum": {"von": "2026-10-01"}, "hauptberuf": "Lagerist/in",
    "firma": "ACME Logistik GmbH", "referenznummer": "10001-1-S", "entfernung": 2,
}


def handler(request: httpx.Request) -> httpx.Response:
    url, q = request.url, {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
    key = request.headers.get("X-API-Key")
    if url.path.endswith("/pc/v6/jobs"):
        assert key == api.KEY_JOBSUCHE and q["was"] == "Lagerist" and q["arbeitszeit"] == "vz;tz" and q["angebotsart"] == "1"
        return httpx.Response(200, json={"ergebnisliste": [JOB], "maxErgebnisse": 1, "page": 1, "size": 25,
                                         "woOutput": {"bereinigterOrt": "Leipzig"}})
    if url.path.endswith("/pc/v4/jobdetails/MTAwMDEtMS1T"):
        return httpx.Response(200, json=JOB | {"stellenangebotsBeschreibung": "<p>Kommissionieren</p>",
                                               "allianzpartnerName": "arbeitsagentur.de"})
    if url.path.endswith("/orte"):
        return httpx.Response(200, json=[{"breitengrad": 51.33, "laengengrad": 12.37, "name": "Leipzig", "postleitzahl": "04103"}])
    if url.path.endswith("/pc/v1/bildungsangebot"):
        assert key == api.KEY_NOW_SUCHE and q["ort"] == "Leipzig_04103_12.37_51.33" and q["uk"] == "25"
        return httpx.Response(200, json={"_embedded": {"bildungsangebotDTOList": [{
            "id": 1, "titel": "Staplerschein", "inhalt": "<p>Gabelstapler &amp; Sicherheit</p>",
            "bildungsanbieter": {"name": "Kurs GmbH", "adresse": {"plz": "04109", "ort": "Leipzig"}},
            "termine": [{"id": "t1_kursnet", "beginn": 1794178800000, "ende": 1794438000000, "adresse": {"ort": "Leipzig"},
                         "unterrichtsform": {"bezeichnung": "Präsenz"}}]}]}, "page": {"totalElements": 1, "number": 0}})
    if url.path.endswith("/berufe/58780"):
        return httpx.Response(200, json=[{"id": 58780, "bezeichnungNeutral": "Lagerist/Lageristin", "kldb2010": "B 51312",
                                          "infofelder": [{"id": "b50-0", "ueberschrift": "Verdienst/Einkommen", "content": "<p>Viel</p>"},
                                                         {"id": "b16-3", "ueberschrift": "Arbeitsbedingungen im Einzelnen", "content": "x"}]}])
    if url.path.endswith("/entgelte/51312"):
        assert key == api.KEY_ENTGELTATLAS and q.get("r") == "17"
        row = {"entgelt": 2900, "entgeltQ25": 2500, "entgeltQ75": 3300, "besetzung": 1000,
               "region": {"bezeichnung": "Sachsen", "beitragsBemessungsGrenze": 8050}, "branche": {"id": 1, "bezeichnung": "Gesamt"},
               "performanceLevel": {"bezeichnung": "Fachkraft"}, "gender": {"bezeichnung": "Gesamt"}, "ageCategory": {"bezeichnung": "Gesamt"}}
        return httpx.Response(200, json=[row, row | {"branche": {"id": 4, "bezeichnung": "Bau"}}, row | {"entgelt": -1}])
    if url.path.endswith("/regionen"):
        return httpx.Response(200, json=[{"id": 1, "bezeichnung": "Deutschland", "schluessel": "D"},
                                         {"id": 17, "bezeichnung": "Sachsen", "schluessel": "14"}])
    if url.path.endswith("/dvosearch"):
        assert request.method == "POST" and json.loads(request.content)["q"] == "04109" and key == api.KEY_DVOSUCHE
        return httpx.Response(200, json={"data": [
            {"dienststellenType": "Arbeitsagenturen", "identifier": "1", "title": "Agentur für Arbeit Leipzig",
             "visitingAddress": {"street": "Georg-Schumann-Str. 150", "zipCode": "04159", "city": "Leipzig"}},
            {"dienststellenType": "Jobcenter", "identifier": "2", "title": "Jobcenter Leipzig", "visitingAddress": {}}]})
    return httpx.Response(404)


@pytest.fixture
def server(store):
    client = api.BAClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return create_server(store=store, client=client)


async def test_search_and_record_application(server, store):
    async with Client(server) as c:
        res = await c.call_tool("search_jobs", {"what": "Lagerist", "where": "Leipzig", "offer_type": "arbeit",
                                                "working_time": ["vollzeit", "teilzeit"]})
        job = res.structured_content["jobs"][0]
        assert job["location"] == "04109 Leipzig" and job["url"].endswith("10001-1-S")
        detail = await c.call_tool("get_job", {"reference_number": "10001-1-S"})
        assert detail.structured_content["description"] == "Kommissionieren"
        added = await c.call_tool("add_application", {"reference_number": "10001-1-S", "applied_on": "2026-10-14",
                                                      "channel": "online"})
        app = added.structured_content["application"]
        assert app["employer"] == "ACME Logistik GmbH" and app["employer_address"] == "Hauptstr. 1, 04109 Leipzig"
        missing = await c.call_tool("get_job", {"reference_number": "nope"})
        assert missing.is_error and "No job" in missing.content[0].text
    assert store.list_applications()[0]["position"] == "Lagerist (m/w/d)"


async def test_courses_professions_salaries_offices(server):
    async with Client(server) as c:
        courses = (await c.call_tool("search_courses", {"keyword": "Stapler", "location": "Leipzig"})).structured_content
        assert courses["courses"][0]["summary"] == "Gabelstapler & Sicherheit"
        assert courses["courses"][0]["dates"][0]["id"] == "t1_kursnet"
        prof = (await c.call_tool("get_profession", {"profession_id": 58780})).structured_content
        assert prof["salary_kldb_code"] == "51312" and prof["sections"] == {"Verdienst/Einkommen": "Viel"}
        sal = (await c.call_tool("get_salaries", {"kldb": prof["kldb2010"], "region": "Sachsen"})).structured_content
        assert [r["median_gross_monthly_eur"] for r in sal["rows"]] == [2900]
        bad = await c.call_tool("get_salaries", {"kldb": "51312", "region": "Atlantis"})
        assert bad.is_error and "Unknown region" in bad.content[0].text
        offices = (await c.call_tool("find_offices", {"query": "04109", "kinds": ["Jobcenter"]})).structured_content
        assert [o["name"] for o in offices["offices"]] == ["Jobcenter Leipzig"]


async def test_case_file_tools(server):
    async with Client(server) as c:
        await c.call_tool("update_profile", {"fields": {"name": "Erika Mustermann", "state": "Sachsen", "benefit": "alg"}})
        bad = await c.call_tool("update_profile", {"fields": {"benefit": "lotto"}})
        assert bad.is_error and "benefit" in bad.content[0].text
        logged = (await c.call_tool("log_correspondence", {"date": "2026-10-09", "kind": "bescheid",
                                                           "subject": "Sperrzeit"})).structured_content
        assert logged["objection_deadline"]["deadline"] == "2026-11-13"
        ov = (await c.call_tool("overview", {})).structured_content
        assert any("Widerspruchsfrist" in d["what"] for d in ov["deadlines"])
        letter = await c.call_tool("draft_letter", {"kind": "widerspruch", "params": {
            "decision_date": "2026-10-09", "decision_subject": "eine Sperrzeit"}, "log": True})
        assert "Erika Mustermann" in letter.content[0].text
        rules = await c.call_tool("rules", {"topic": "sperrzeit"})
        assert "§ 159" in rules.content[0].text
        reg = (await c.call_tool("registration_deadlines", {"employment_end": "2026-06-30",
                                                            "learned_on": "2026-01-15"})).structured_content
        assert reg["arbeitsuchend_melden"]["deadline"] == "2026-03-31"
