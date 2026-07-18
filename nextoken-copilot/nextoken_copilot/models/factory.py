"""Pluggable chat-model factory.

``COPILOT_LLM_MODE`` selects the backend used by every agent in the system:

    sandbox    (default) fully offline, deterministic — no key, no network
    gateway    NexToken's own OpenAI-compatible /v1 endpoint  (dogfood)
    openai     OpenAI directly
    anthropic  Anthropic
    bedrock    Amazon Bedrock

Only ``sandbox`` is installed by default; the others need the matching extra
listed in requirements.txt plus a key/endpoint in the environment.
"""
from __future__ import annotations

from ..config import settings


def _model_name(tier: str | None) -> str:
    """Pick the model for a tier: 'router' (plan/route/tools) or 'answer'."""
    if tier == "router" and settings.router_model:
        return settings.router_model
    if tier == "answer" and settings.answer_model:
        return settings.answer_model
    return settings.llm_model


def get_chat_model(tier: str | None = None):
    """Return a chat model. ``tier`` enables the router/answer split.

    In sandbox mode the tier is ignored (one deterministic model). With a real
    backend, point COPILOT_ROUTER_MODEL at a small/fine-tuned model and
    COPILOT_ANSWER_MODEL at a stronger one to cut cost and latency.
    """
    mode = settings.llm_mode.lower()

    if mode == "sandbox":
        from .sandbox import SandboxChatModel

        return SandboxChatModel()

    model_name = _model_name(tier)

    if mode in ("gateway", "openai"):
        # The NexToken gateway is OpenAI-compatible, so the same client works.
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_name,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "not-needed",
            temperature=settings.llm_temperature,
        )

    if mode == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model_name, temperature=settings.llm_temperature)

    if mode == "bedrock":
        from langchain_aws import ChatBedrockConverse

        return ChatBedrockConverse(model=model_name, temperature=settings.llm_temperature)

    raise ValueError(f"Unknown COPILOT_LLM_MODE: {settings.llm_mode!r}")
