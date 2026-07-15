"""FastAPI surface for the nextoken_copilot.

    uvicorn nextoken_copilot.api:app --port 8088

POST /assistant/chat is guarded by :func:`principal_from_request`; the resolved
Principal is the only identity the agents ever see. GET /app serves the chat
panel. CORS is open in dev so the panel can also be embedded in the NexToken
console (restrict COPILOT_CORS_ORIGINS in production).
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .agents.graph import answer
from .auth import DEV_AUTH, create_token, principal_from_request
from .principal import Principal, Role

app = FastAPI(title="NexToken Copilot", version="0.1.0")

_ORIGINS = os.getenv("COPILOT_CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

_PANEL = Path(__file__).resolve().parent.parent / "web" / "assistant.html"

# In-process conversation memory (Context layer). A production build would use
# the backend's customer_chat_conversations tables; this keeps the demo simple.
_MEMORY: dict[str, list[dict]] = {}
_MAX_TURNS = 6


def _context(conversation_id: str | None) -> str:
    turns = _MEMORY.get(conversation_id or "", [])[-_MAX_TURNS:]
    return "\n".join(f"Q: {t['q']}\nA: {t['a'][:200]}" for t in turns)


class ChatBody(BaseModel):
    question: str
    conversation_id: str | None = None
    images: list[str] | None = None  # data URLs or URLs; read by the vision front door
    language: str | None = None      # locale hint for the answer, e.g. "zh-Hant", "ar", "hi"


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "dev_auth": DEV_AUTH}


@app.get("/", response_class=HTMLResponse)
@app.get("/app", response_class=HTMLResponse)
def panel() -> str:
    return _PANEL.read_text(encoding="utf-8")


@app.post("/assistant/chat")
async def chat(
    body: ChatBody,
    principal: Principal = Depends(principal_from_request),
    authorization: str | None = Header(default=None),
) -> dict:
    # In remote tools mode the caller's own JWT flows through to the NexToken
    # backend, which re-enforces RBAC and audits every tool call server-side.
    token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else None
    context = _context(body.conversation_id)
    result = await answer(principal, body.question, token=token, context=context,
                          images=body.images, language=body.language)
    if body.conversation_id:
        _MEMORY.setdefault(body.conversation_id, []).append({"q": body.question, "a": result["answer"]})
    return {"role": principal.role.value, "question": body.question, **result}


if DEV_AUTH:
    class TokenBody(BaseModel):
        role: str
        customer_id: int | None = None

    @app.post("/dev/token")
    def dev_token(body: TokenBody) -> dict:
        """Mint a demo JWT (dev only)."""
        return {"token": create_token(Role(body.role), body.customer_id)}
