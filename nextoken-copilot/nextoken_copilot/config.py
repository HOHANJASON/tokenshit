"""Central configuration for NexToken Copilot.

Everything that decides *where data comes from* and *which LLM the agents run
on* lives here, so the rest of the codebase never reads ``os.environ`` directly.
Switching from the offline sandbox model to the real NexToken gateway is a
one-line env change (``COPILOT_LLM_MODE=gateway``).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "nextoken_sample.db"


@dataclass(frozen=True)
class Settings:
    # --- data source -------------------------------------------------------
    database_url: str = os.getenv("COPILOT_DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")

    # --- LLM runtime -------------------------------------------------------
    # one of: sandbox | gateway | openai | anthropic | bedrock
    llm_mode: str = os.getenv("COPILOT_LLM_MODE", "sandbox")
    llm_model: str = os.getenv("COPILOT_LLM_MODEL", "nxt-gpt-4o-mini")
    # Inference optimization: a cheap/small (optionally fine-tuned) model handles
    # planning/routing/tool-selection; a stronger one writes the final answer.
    # Empty => fall back to llm_model for both.
    router_model: str = os.getenv("COPILOT_ROUTER_MODEL", "")
    answer_model: str = os.getenv("COPILOT_ANSWER_MODEL", "")
    # OpenAI-compatible base url + key (NexToken gateway by default).
    llm_base_url: str = os.getenv("COPILOT_LLM_BASE_URL", "http://127.0.0.1:3100/v1")
    llm_api_key: str = os.getenv("COPILOT_LLM_API_KEY", "")
    llm_temperature: float = float(os.getenv("COPILOT_LLM_TEMPERATURE", "0"))

    # --- tool source -------------------------------------------------------
    # local  = reference data layer via our MCP server (offline dev)
    # remote = the real NexToken backend's audited /api/assistant/tools surface
    tools_mode: str = os.getenv("COPILOT_TOOLS_MODE", "local")
    backend_url: str = os.getenv("COPILOT_BACKEND_URL", "http://127.0.0.1:3100")
    backend_token: str = os.getenv("COPILOT_BACKEND_TOKEN", "")

    # --- guardrails --------------------------------------------------------
    max_rows: int = int(os.getenv("COPILOT_MAX_ROWS", "200"))

    # --- monitoring / feedback loop ---------------------------------------
    # If set, every request appends a JSONL trace (role, plan, routes, tools,
    # latency) — the dataset source for router fine-tuning later.
    trace_file: str = os.getenv("COPILOT_TRACE_FILE", "")


settings = Settings()
