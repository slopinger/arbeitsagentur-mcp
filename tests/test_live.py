"""Smoke tests against the real public APIs. Run with: uv run pytest -m live"""
import pytest

from arbeitsagentur_mcp.api import BAClient

pytestmark = pytest.mark.live


@pytest.fixture
async def ba():
    c = BAClient()
    yield c
    await c.aclose()


async def test_jobs(ba):
    res = await ba.search_jobs("Python", "Berlin", size=3)
    assert res["total"] > 0
    detail = await ba.job_details(res["jobs"][0]["reference_number"])
    assert detail["title"]


async def test_courses(ba):
    res = await ba.search_courses("Python", "Leipzig", radius_km=50, size=3)
    assert res["total"] > 0
    date_id = next(d["id"] for c in res["courses"] for d in c.get("dates", []))
    assert (await ba.course_details(date_id))["title"]


async def test_profession_and_salary(ba):
    res = await ba.search_professions("Fachinformatiker", 5)
    prof = await ba.profession(res["professions"][0]["profession_id"])
    sal = await ba.salaries(prof["salary_kldb_code"])
    assert sal["rows"]


async def test_offices(ba):
    res = await ba.search_offices("10117")
    assert any(o["kind"] == "Jobcenter" for o in res["offices"])
