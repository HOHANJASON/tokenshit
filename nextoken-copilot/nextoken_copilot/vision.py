"""Multimodal front door.

A customer can attach an image (a screenshot of an error, an invoice, a
dashboard). Before the multi-agent pipeline runs, we send the image(s) to a
**vision-capable model through the NexToken gateway** and get back a plain-text
description. That description is folded into the question, so the rest of the
system — orchestrator, workers, tools, aggregator — stays entirely text and
needs no changes.

Why through the gateway: the gateway is OpenAI-compatible and already forwards
``image_url`` content, so the vision model is just another NexToken model
(``COPILOT_VISION_MODEL``). It's local (Ollama) for the demo and swaps to a
cloud vision provider in production with no code change. Identity/billing ride
the same customer key as every other gateway call.
"""
from __future__ import annotations

import httpx

from .config import settings

# Keep the vision call cheap and bounded — it's a pre-step, not the answer.
_MAX_IMAGES = 3
_TIMEOUT = 60


def _sandbox_description(n: int) -> str:
    """Deterministic stand-in when no real vision model is configured."""
    return f"[sandbox vision] {n} image(s) attached; no vision model configured."


async def describe_images(images: list[str], question: str) -> str:
    """Return a text description of the attached images, or '' if none/disabled.

    ``images`` are data URLs (``data:image/...;base64,...``) or plain URLs.
    """
    images = [i for i in (images or []) if i][:_MAX_IMAGES]
    if not images:
        return ""
    if settings.llm_mode.lower() == "sandbox" or not settings.vision_model:
        return _sandbox_description(len(images))

    content = [{
        "type": "text",
        "text": ("You are helping a NexToken API customer. Describe what this "
                 "screenshot shows in 1-3 sentences — quote any error codes, "
                 "numbers, model names or messages exactly. The customer asked: "
                 f"{question!r}"),
    }]
    for url in images:
        content.append({"type": "image_url", "image_url": {"url": url}})

    payload = {
        "model": settings.vision_model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
    }
    headers = {"Authorization": f"Bearer {settings.llm_api_key or 'not-needed'}"}
    async with httpx.AsyncClient(base_url=settings.llm_base_url, timeout=_TIMEOUT) as client:
        resp = await client.post("/chat/completions", json=payload, headers=headers)
    if resp.status_code >= 400:
        return f"[vision unavailable: HTTP {resp.status_code}]"
    data = resp.json()
    return (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
