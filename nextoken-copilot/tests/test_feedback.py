"""Thumbs+trace feedback loop: answer_id on every chat, votes recorded as JSONL."""
import json
import warnings

warnings.filterwarnings("ignore")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import nextoken_copilot.api as api  # noqa: E402

client = TestClient(api.app)
HEADERS = {"X-Role": "client", "X-Customer-Id": "1"}


@pytest.fixture
def feedback_dir(_feedback_dir):
    """The suite-wide tmp feedback dir (redirected in conftest.py)."""
    return _feedback_dir


def _read(path):
    return [json.loads(l) for l in path.read_text().splitlines()]


def test_chat_returns_answer_id_and_logs_trace(feedback_dir):
    r = client.post("/assistant/chat", json={"question": "what is my balance"}, headers=HEADERS)
    assert r.status_code == 200
    answer_id = r.json()["answer_id"]
    assert answer_id and answer_id.isalnum()

    traces = _read(feedback_dir / "feedback_traces.jsonl")
    assert traces[-1]["answer_id"] == answer_id
    assert traces[-1]["question"] == "what is my balance"
    assert traces[-1]["role"] == "client"
    assert traces[-1]["plan"]


def test_vote_up_and_down_recorded(feedback_dir):
    answer_id = client.post("/assistant/chat", json={"question": "what is my balance"},
                            headers=HEADERS).json()["answer_id"]
    for verdict in ("up", "down"):
        r = client.post("/assistant/feedback",
                        json={"answer_id": answer_id, "verdict": verdict}, headers=HEADERS)
        assert r.status_code == 200 and r.json()["ok"]

    votes = _read(feedback_dir / "feedback_votes.jsonl")
    assert [v["verdict"] for v in votes] == ["up", "down"]
    assert votes[0]["answer_id"] == answer_id
    assert votes[0]["customer_id"] == 1


def test_comment_is_sanitized(feedback_dir):
    r = client.post("/assistant/feedback",
                    json={"answer_id": "abc123", "verdict": "down",
                          "comment": "wrong b​alance shown"}, headers=HEADERS)
    assert r.status_code == 200
    votes = _read(feedback_dir / "feedback_votes.jsonl")
    assert votes[-1]["comment"] == "wrong balance shown"  # zero-width char stripped


def test_feedback_requires_auth_and_valid_body():
    assert client.post("/assistant/feedback",
                       json={"answer_id": "abc123", "verdict": "up"}).status_code == 401
    bad = client.post("/assistant/feedback",
                      json={"answer_id": "abc123", "verdict": "meh"}, headers=HEADERS)
    assert bad.status_code == 422
    bad_id = client.post("/assistant/feedback",
                         json={"answer_id": "../../etc", "verdict": "up"}, headers=HEADERS)
    assert bad_id.status_code == 422
