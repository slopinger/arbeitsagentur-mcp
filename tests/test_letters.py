import pytest

from arbeitsagentur_mcp import letters

PROFILE = {"name": "Erika Mustermann", "address": "Musterweg 1, 04109 Leipzig", "customer_number": "123A456789",
           "benefit": "alg", "agency": "Agentur für Arbeit Leipzig, Georg-Schumann-Str. 150, 04159 Leipzig"}


def test_widerspruch_without_reasons_requests_file_access():
    letter = letters.render("widerspruch", PROFILE, {"decision_date": "2026-10-09",
                                                     "decision_subject": "eine Sperrzeit", "date": "2026-10-14"})
    assert letter.subject == "Widerspruch gegen den Bescheid vom 09.10.2026"
    t = letter.text
    assert t.startswith("Erika Mustermann\nMusterweg 1\n04109 Leipzig\n")
    assert "Agentur für Arbeit Leipzig\nGeorg-Schumann-Str. 150\n04159 Leipzig" in t
    assert "Leipzig, 14.10.2026" in t and "Kundennummer: 123A456789" in t
    assert "Akteneinsicht nach § 25 SGB X" in t


def test_widerspruch_with_reasons():
    t = letters.render("widerspruch", PROFILE, {"decision_date": "09.10.2026", "decision_subject": "X",
                                                "reasons": "Ich hatte einen wichtigen Grund."}).text
    assert "Begründung:\nIch hatte einen wichtigen Grund." in t and "Akteneinsicht" not in t


def test_jobcenter_recipient_for_grundsicherung():
    p = PROFILE | {"benefit": "grundsicherung", "jobcenter": "Jobcenter Leipzig, Postfach 1, 04001 Leipzig",
                   "bg_number": "12345BG0000001"}
    t = letters.render("veraenderungsmitteilung", p, {"change": "Umzug", "effective_date": "2026-11-01"}).text
    assert "Jobcenter Leipzig" in t and "BG-Nummer: 12345BG0000001" in t


@pytest.mark.parametrize("kind", list(letters.LETTERS))
def test_all_letters_validate_params(kind):
    if kind == "akteneinsicht":
        assert letters.render(kind, {}, {}).text
        return
    with pytest.raises(ValueError, match="Missing parameter"):
        letters.render(kind, {}, {})


def test_unknown_kind():
    with pytest.raises(ValueError):
        letters.render("liebesbrief", {}, {})
