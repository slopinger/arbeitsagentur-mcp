import pytest

from arbeitsagentur_mcp.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "akte.sqlite3")
    yield s
    s.close()
