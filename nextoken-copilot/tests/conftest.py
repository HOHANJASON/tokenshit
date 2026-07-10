import pytest

from nextoken_copilot import seed


@pytest.fixture(scope="session", autouse=True)
def _seed_db():
    """Deterministically (seed=7) (re)build the sample DB before the suite runs."""
    seed.main()
    yield
