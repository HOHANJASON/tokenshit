"""Product-knowledge layer for the ``help`` worker.

A tiny, deterministic RAG: the markdown files in ``nextoken_copilot/docs/``
are split into sections by ``##`` heading, and ``search_docs`` returns the
sections whose words best overlap the query. No embeddings, no network —
it runs offline (sandbox mode included) and is fully reproducible.

The docs are PUBLIC product documentation, so the tool is role-agnostic:
unlike the data tools it needs no JWT and can never leak account data.
"""
from __future__ import annotations

import re
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

DOCS_DIR = Path(__file__).resolve().parent / "docs"

_STOPWORDS = {
    "a", "an", "the", "i", "my", "me", "is", "are", "am", "do", "does", "how",
    "what", "why", "when", "to", "of", "in", "on", "for", "and", "or", "it",
    "with", "get", "getting", "can", "you", "your",
}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS}


def _load_sections() -> list[dict]:
    """Split every doc into {doc, heading, text} sections on '##' headings."""
    sections = []
    for path in sorted(DOCS_DIR.glob("*.md")):
        doc_title = path.stem
        heading, lines = "", []
        for line in path.read_text(encoding="utf-8").splitlines() + ["## _end"]:
            if line.startswith("## "):
                if lines:
                    text = "\n".join(lines).strip()
                    if text:
                        sections.append({"doc": doc_title, "heading": heading, "text": text})
                heading, lines = line[3:].strip(), []
            elif not line.startswith("# "):
                lines.append(line)
    return sections


_SECTIONS = _load_sections()


def search_docs(query: str = "") -> str:
    """Return the top documentation sections for a product/how-to question."""
    q = _words(query or "")
    scored = []
    for s in _SECTIONS:
        score = len(q & _words(s["heading"])) * 2 + len(q & _words(s["text"]))
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda t: -t[0])
    if not scored:
        return ("No matching documentation found. Topics covered: quickstart, "
                "authentication and API keys, errors and rate limits, billing "
                "and balance, features (tool calling, streaming).")
    return "\n\n".join(f"[{s['doc']} / {s['heading']}]\n{s['text']}" for _, s in scored[:3])


class _SearchArgs(BaseModel):
    query: str = Field("", description="The user's question or keywords to look up in the docs.")


def load_help_tools() -> list[StructuredTool]:
    """The help worker's tool surface (available in every tools mode)."""
    return [
        StructuredTool.from_function(
            func=search_docs,
            name="search_docs",
            description="Search NexToken's product documentation: quickstart and SDK "
                        "integration, authentication and API keys, error codes and "
                        "rate limits (401/402/429), billing, tool calling, streaming.",
            args_schema=_SearchArgs,
        )
    ]
