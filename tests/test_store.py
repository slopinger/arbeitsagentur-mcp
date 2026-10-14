import csv
import io
import os
import stat
from datetime import date, timedelta

import pytest


def test_db_file_is_private(store):
    assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600


def test_profile_roundtrip(store):
    p = store.update_profile({"name": "Erika Mustermann", "employment_end": "31.12.2026", "state": "SN"})
    assert p["employment_end"] == "2026-12-31"
    p = store.update_profile({"state": ""})
    assert "state" not in p
    with pytest.raises(ValueError):
        store.update_profile({"shoe_size": "42"})


def test_application_defaults(store):
    planned = store.add_application(employer="ACME", position="Lagerist")
    assert planned["status"] == "geplant" and "applied_on" not in planned
    done = store.add_application(employer="ACME", position="Fahrer", applied_on="2026-10-01", channel="email")
    assert done["status"] == "beworben" and done["applied_on"] == "2026-10-01"
    proposal = store.add_application(employer="BA-Partner", position="Koch", source="vermittlungsvorschlag",
                                     proposal_received_on="2026-10-12")
    assert proposal["apply_by"] == "2026-10-15"
    with pytest.raises(ValueError):
        store.add_application(employer="X", position="Y", source="telepathie")


def test_update_application_sets_dates(store):
    a = store.add_application(employer="ACME", position="Lagerist")
    u = store.update_application(a["id"], status="beworben")
    assert u["applied_on"] == date.today().isoformat()
    u = store.update_application(a["id"], status="absage", status_date="2026-10-20", notes="Absage per Mail")
    assert u["status"] == "absage" and u["status_date"] == "2026-10-20" and u["notes"] == "Absage per Mail"
    with pytest.raises(KeyError):
        store.update_application(999, status="absage")


def test_proof_of_applications(store):
    store.update_profile({"name": "Erika Mustermann", "customer_number": "123A456789"})
    store.add_application(employer="ACME | GmbH", employer_address="Hauptstr. 1, 04109 Leipzig", position="Fahrer",
                          applied_on="2026-10-01", channel="email", reference_number="10001-1-S")
    store.add_application(employer="Beta AG", position="Lagerist", applied_on="2026-10-05", status="absage")
    store.add_application(employer="Out of range", position="X", applied_on="2026-09-30")
    store.add_application(employer="Planned", position="Y")
    md = store.proof_of_applications("2026-10-01", "2026-10-31")
    assert "Erika Mustermann" in md and "123A456789" in md
    assert "ACME / GmbH, Hauptstr. 1, 04109 Leipzig" in md and "Ref. 10001-1-S" in md
    assert "Out of range" not in md and "Planned" not in md
    assert "**Anzahl Bewerbungen:** 2" in md
    rows = list(csv.reader(io.StringIO(store.proof_of_applications("01.10.2026", "31.10.2026", "csv")), delimiter=";"))
    assert len(rows) == 3 and rows[1][1] == "01.10.2026"


def test_appointments(store):
    a = store.add_appointment(starts_at="20.10.2099 09:30", kind="meldetermin", location="Agentur Leipzig")
    assert a["starts_at"] == "2099-10-20T09:30"
    assert [x["id"] for x in store.list_appointments()] == [a["id"]]
    store.update_appointment(a["id"], status="wahrgenommen", notes="ok")
    assert store.list_appointments() == []
    with pytest.raises(ValueError):
        store.add_appointment(starts_at="morgen", kind="meldetermin")


def test_overview_alerts(store):
    today = date(2026, 10, 14)
    store.update_profile({"applications_per_month": "5", "employment_end": "2026-11-30"})
    store.add_application(employer="A", position="P", applied_on="2026-10-02")
    store.add_application(employer="Old", position="P", applied_on="2026-09-01")
    store.add_application(employer="VV", position="Koch", source="vermittlungsvorschlag",
                          proposal_received_on="2026-10-10", apply_by="2026-10-13")
    done = store.add_application(employer="VV2", position="Koch", source="vermittlungsvorschlag",
                                 applied_on="2026-10-01")
    store.update_application(done["id"], status="absage")
    store.add_correspondence(date="2026-10-01", kind="bescheid", subject="Bewilligung", objection_deadline="2026-11-05",
                             objection_status="offen")
    store.add_appointment(starts_at="2026-10-20T10:00", kind="beratung")
    store.add_appointment(starts_at="2026-10-01T10:00", kind="meldetermin")
    store.add_task(title="Lebenslauf schicken", due="2026-10-16")
    ov = store.overview(today=today)
    alerts = "\n".join(ov["alerts"])
    assert "ÜBERFÄLLIG seit 1 Tag(en): Bewerbung auf Vermittlungsvorschlag" in alerts
    assert "Fällig in 2 Tag(en): Aufgabe" in alerts
    assert "noch nicht zurückgemeldet" in alerts
    assert "steht noch auf 'geplant'" in alerts
    assert "Noch 3 Bewerbung(en)" in alerts
    assert "Arbeitsuchendmeldung" in alerts
    assert "Arbeitslosmeldung spätestens am 01.12.2026" in alerts
    assert ov["applications"]["applications_this_month"] == 2
    assert [a["kind"] for a in ov["upcoming_appointments"]] == ["beratung"]
    assert ov["deadlines"][0]["due"] == "2026-10-13"
    assert ov["applications"]["no_answer_for_4_weeks"][0]["employer"] == "Old"


def test_correspondence_and_tasks(store):
    c = store.add_correspondence(date="2026-10-01", kind="bescheid", subject="Sperrzeit", reference="AZ 1")
    store.update_correspondence(c["id"], objection_status="eingelegt")
    assert store.list_correspondence(query="AZ 1")[0]["objection_status"] == "eingelegt"
    t = store.add_task(title="Antwort Anhörung", due=(date.today() + timedelta(days=3)).isoformat())
    store.complete_task(t["id"])
    assert store.list_tasks() == [] and len(store.list_tasks(include_done=True)) == 1
    store.delete("task", t["id"])
    assert store.list_tasks(include_done=True) == []
    with pytest.raises(ValueError):
        store.delete("profile", 1)
