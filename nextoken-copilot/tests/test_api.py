"""API auth + role behaviour."""
import warnings

warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from nextoken_copilot.api import app  # noqa: E402

client = TestClient(app)


def test_health():
    assert client.get("/health").json()["status"] == "ok"


def test_chat_requires_auth():
    assert client.post("/assistant/chat", json={"question": "x"}).status_code == 401
    assert client.post("/assistant/chat", json={"question": "x"},
                       headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_client_chat_with_dev_header():
    r = client.post("/assistant/chat", json={"question": "what is my balance"},
                    headers={"X-Role": "client", "X-Customer-Id": "1"})
    assert r.status_code == 200
    assert "balance" in r.json()["answer"].lower()


def test_admin_chat_with_jwt():
    token = client.post("/dev/token", json={"role": "admin"}).json()["token"]
    r = client.post("/assistant/chat", json={"question": "revenue and gross margin this month"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert "gross_margin" in r.json()["answer"].lower()
