"""Public entry points for the multi-agent system."""
from __future__ import annotations

import asyncio

from ..principal import Principal
from .graph import answer


def ask(principal: Principal, question: str) -> dict:
    """Synchronous convenience wrapper around :func:`answer`."""
    return asyncio.run(answer(principal, question))


__all__ = ["answer", "ask", "Principal"]
