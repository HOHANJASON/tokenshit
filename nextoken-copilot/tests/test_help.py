"""The help worker: product-docs questions answered via search_docs."""
from nextoken_copilot.agents import ask
from nextoken_copilot.knowledge import search_docs
from nextoken_copilot.principal import Principal, Role


def _client() -> Principal:
    return Principal(role=Role.CLIENT, customer_id=1, email="eval@local")


def test_search_docs_finds_429_section():
    text = search_docs("why am I getting 429 errors")
    assert "429" in text
    assert "rate limit" in text.lower()


def test_search_docs_handles_no_match():
    assert "Topics covered" in search_docs("zzz qqq")


def test_help_worker_answers_how_to_question():
    result = ask(_client(), "How do I authenticate my API requests?")
    assert "help" in result["metrics"]["workers"]
    assert "search_docs" in result["metrics"]["tools_called"]
    assert "authorization" in result["answer"].lower() or "bearer" in result["answer"].lower()


def test_help_worker_explains_429():
    result = ask(_client(), "Why am I getting 429 errors?")
    assert "search_docs" in result["metrics"]["tools_called"]
    assert "rate limit" in result["answer"].lower()
