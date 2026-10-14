from datetime import date

import pytest

from arbeitsagentur_mcp import deadlines as d


@pytest.mark.parametrize("year,expected", [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)),
                                           (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28))])
def test_easter(year, expected):
    assert d.easter_sunday(year) == expected


def test_holidays_national_and_state():
    national = d.public_holidays(2026)
    assert national[date(2026, 4, 3)] == "Karfreitag"
    assert national[date(2026, 5, 14)] == "Christi Himmelfahrt"
    assert date(2026, 6, 4) not in national  # Fronleichnam is not nationwide
    assert d.public_holidays(2026, "Bayern")[date(2026, 6, 4)] == "Fronleichnam"
    assert d.public_holidays(2026, "SN")[date(2026, 11, 18)] == "Buß- und Bettag"
    assert d.public_holidays(2025, "SN")[date(2025, 11, 19)] == "Buß- und Bettag"
    assert date(2026, 10, 31) not in d.public_holidays(2026, "nrw")
    assert date(2026, 10, 31) in d.public_holidays(2026, "HH")
    assert d.public_holidays(2026, "TH")[date(2026, 9, 20)] == "Weltkindertag"


def test_unknown_state():
    with pytest.raises(ValueError):
        d.normalize_state("Atlantis")


def test_add_months_clamps():
    assert d.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert d.add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert d.add_months(date(2026, 7, 1), -3) == date(2026, 4, 1)
    assert d.add_months(date(2026, 11, 15), 2) == date(2027, 1, 15)


def test_period_end_shifts_weekend_and_holiday():
    assert d.period_end(date(2026, 5, 4), months=1).deadline == date(2026, 6, 4)
    assert d.period_end(date(2026, 5, 4), months=1, state="BY").deadline == date(2026, 6, 5)
    assert d.period_end(date(2026, 1, 31), months=1).deadline == date(2026, 3, 2)  # Sat 28.02. -> Mon
    assert d.period_end(date(2026, 10, 14), weeks=2).deadline == date(2026, 10, 28)


def test_objection_deadline_post_2025():
    res = d.objection_deadline(date(2026, 10, 9))  # posted Fri, deemed notified Tue 13.10.
    assert res.deadline == date(2026, 11, 13)
    assert any("4. Tag" in s for s in res.steps)


def test_objection_deadline_new_year():
    # notified 01.12.2026, one month later is Neujahr 2027 (Friday) -> Monday 04.01.2027
    assert d.objection_deadline(date(2026, 11, 27)).deadline == date(2027, 1, 4)


def test_objection_deadline_old_rule_and_late_receipt():
    assert d.objection_deadline(date(2024, 12, 20)).deadline == date(2025, 1, 23)
    late = d.objection_deadline(date(2026, 10, 9), received=date(2026, 10, 20))
    assert late.deadline == date(2026, 11, 20)
    early = d.objection_deadline(date(2026, 10, 9), received=date(2026, 10, 10))
    assert early.deadline == date(2026, 11, 13)


def test_objection_deadline_personal_and_missing_instruction():
    assert d.objection_deadline(date(2026, 10, 14), delivery="personal").deadline == date(2026, 11, 16)  # 14.11. is Sat
    year = d.objection_deadline(date(2026, 10, 9), legal_remedy_instruction_ok=False)
    assert year.deadline == date(2027, 10, 13)


def test_job_seeker_registration():
    early = d.job_seeker_registration(date(2026, 6, 30), date(2026, 1, 15))
    assert early.deadline == date(2026, 3, 31)
    short = d.job_seeker_registration(date(2026, 6, 30), date(2026, 5, 1))
    assert short.deadline == date(2026, 5, 4)
    weekend = d.job_seeker_registration(date(2026, 6, 30), date(2026, 5, 7))
    assert weekend.deadline == date(2026, 5, 11)
    with pytest.raises(ValueError):
        d.job_seeker_registration(date(2026, 6, 30), date(2026, 7, 1))


def test_unemployment_registration():
    assert d.unemployment_registration(date(2026, 12, 31)).deadline == date(2027, 1, 1)


@pytest.mark.parametrize("months,age,expected", [(11, 30, 0), (12, 30, 6), (24, 40, 12), (30, 49, 12),
                                                 (30, 52, 15), (48, 57, 18), (48, 58, 24), (60, 64, 24)])
def test_alg_duration(months, age, expected):
    assert d.alg_entitlement_months(months, age)["entitlement_months"] == expected


def test_alg_duration_requires_anwartschaft():
    res = d.alg_entitlement_months(40, 50, months_insured_30m=8)
    assert res["entitled"] is False
