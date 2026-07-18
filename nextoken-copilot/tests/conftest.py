import pytest

from nextoken_copilot import seed


@pytest.fixture(scope="session", autouse=True)
def _seed_db():
    """Deterministically (seed=7) (re)build the sample DB before the suite runs."""
    seed.main()
    yield


@pytest.fixture(autouse=True)
def _feedback_dir(tmp_path, monkeypatch):
    """Keep feedback JSONL out of the real data/ dir during tests."""
    import nextoken_copilot.api as api
    monkeypatch.setattr(api, "_FEEDBACK_DIR", tmp_path)
    return tmp_path
