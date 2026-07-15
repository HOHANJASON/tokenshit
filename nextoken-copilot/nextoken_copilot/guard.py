"""Output guardrail — a final safety net on the aggregated answer.

Input-side tool scoping is the primary defence (a role's agent can't call a tool
it isn't allowed). This is defence in depth for the day a *real* model writes the
prose. Three concerns are handled:

1. **RBAC leak** — scan for internal field names a role must never receive; if any
   slipped through, replace the whole answer with a safe refusal.
2. **Link guard (anti-phishing)** — strip any URL whose host is not on the
   NexToken allowlist, so a link planted via an image / doc / customer field is
   never relayed to the customer as if it were official.
3. **Special-character evasion** — a naive substring/regex scan is defeated by
   Unicode tricks: full-width glyphs (``ｇｒｏｓｓ＿ｍａｒｇｉｎ``), zero-width spaces
   splitting a trigger word, homoglyphs, bidi/invisible control chars
   (Trojan-Source), or obfuscated links (``hxxp://evil[.]com``). So every scan
   runs on a *canonicalised* copy (invisible chars stripped, NFKC-folded, link
   obfuscation undone), and the user-facing answer has invisible/bidi chars
   stripped. Legitimate non-ASCII prose (e.g. 繁體中文) is unaffected.

None of this weakens tool-level RBAC — it only catches what reached the text.
"""
from __future__ import annotations

import os
import re
import unicodedata

from .principal import Principal, Role

_FORBIDDEN: dict[Role, list[str]] = {
    Role.CLIENT: ["upstream_cost", "gross_margin", "margin_pct", "api_key_encrypted"],
    Role.SUPPORT: ["upstream_cost", "gross_margin", "margin_pct", "api_key_encrypted"],
    Role.ADMIN: ["api_key_encrypted"],
}

# Extra internal identifiers that must never surface to CUSTOMERS (provider names,
# infra hostnames, upstream model ids, secrets prefixes…). Jason sets these per
# deployment: COPILOT_FORBIDDEN_TOKENS="openai-main,azure-backup,internal.nextoken".
_EXTRA_CUSTOMER_FORBIDDEN = [
    t.strip().lower() for t in os.getenv("COPILOT_FORBIDDEN_TOKENS", "").split(",") if t.strip()
]

_REFUSAL = (
    "I can only share data your role is allowed to see, so I can't include that. "
    "Ask about the information available to your account and I'll help."
)
_LINK_REFUSAL = (
    "My answer referenced a link I can't verify as an official NexToken address, "
    "so I've removed it. Manage your account from the NexToken dashboard directly."
)

# Hosts the copilot may surface a link to. Anything else is stripped as untrusted.
_DEFAULT_ALLOWED = "nextoken.ai,nextoken.io,localhost,127.0.0.1"
_ALLOWED_HOSTS = {
    h.strip().lower()
    for h in os.getenv("COPILOT_LINK_ALLOWLIST", _DEFAULT_ALLOWED).split(",")
    if h.strip()
}
_URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s<>()\[\]{}\"']+", re.IGNORECASE)
_LINK_REMOVED = "[external link removed]"

# Invisible / hiding characters removed before display and before scanning:
# zero-width & joiners, LRM/RLM, bidi embeddings/overrides/isolates (Trojan-Source),
# word joiner, BOM, soft hyphen, and C0/C1 control chars (but keep \t \n \r).
_INVISIBLE_CODES = (
    [0x00AD, 0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2060, 0xFEFF]
    + list(range(0x202A, 0x202F))          # bidi embeddings / overrides
    + list(range(0x2066, 0x206A))          # bidi isolates
    + [c for c in range(0x00, 0x20) if c not in (0x09, 0x0A, 0x0D)]  # C0 controls
    + list(range(0x7F, 0xA0))              # DEL + C1 controls
)
_INVISIBLE_RE = re.compile("[" + "".join(re.escape(chr(c)) for c in _INVISIBLE_CODES) + "]")

# Common link-obfuscation forms → canonical, so the URL regex can see the real host.
_DEOBFUSCATE = [
    (re.compile(r"\bhxxp(s?)\b", re.IGNORECASE), r"http\1"),
    (re.compile(r"[\(\[\{]\s*(?:\.|dot)\s*[\)\]\}]", re.IGNORECASE), "."),
]


def strip_invisibles(text: str) -> str:
    """Remove zero-width / bidi / control characters (safe for real prose)."""
    return _INVISIBLE_RE.sub("", text or "")


def _canon(text: str) -> str:
    """Canonical form used ONLY for detection: de-hidden, NFKC-folded, lowercased."""
    t = strip_invisibles(text)
    t = unicodedata.normalize("NFKC", t)
    for pat, repl in _DEOBFUSCATE:
        t = pat.sub(repl, t)
    return t.lower()


def sanitize_input(text: str) -> str:
    """Ingress hygiene for untrusted text (question / vision output): drop invisible
    and bidi characters that only serve to hide instructions. Visible content is kept."""
    return strip_invisibles(text)


def _host_of(url: str) -> str:
    u = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
    u = re.sub(r"^www\.", "", u, flags=re.IGNORECASE)
    return u.split("/")[0].split(":")[0].split("?")[0].lower()


def _host_allowed(host: str) -> bool:
    return any(host == a or host.endswith("." + a) for a in _ALLOWED_HOSTS)


def _forbidden_for(role: Role) -> list[str]:
    tokens = list(_FORBIDDEN.get(role, []))
    if role in (Role.CLIENT, Role.SUPPORT):  # customer-facing: also block internal ids
        tokens += _EXTRA_CUSTOMER_FORBIDDEN
    return tokens


def scan(role: Role, text: str) -> list[str]:
    """Forbidden field tokens present in ``text`` (matched on the canonical form)."""
    low = _canon(text)
    return [tok for tok in _forbidden_for(role) if tok.lower() in low]


def scan_links(text: str) -> list[str]:
    """Disallowed hosts found in ``text`` (matched on the canonical form)."""
    return [h for url in _URL_RE.findall(_canon(text)) if not _host_allowed(h := _host_of(url))]


def strip_links(text: str) -> str:
    """Replace every disallowed URL (in visible text) with a redaction marker."""
    return _URL_RE.sub(lambda m: m.group(0) if _host_allowed(_host_of(m.group(0))) else _LINK_REMOVED, text or "")


def enforce(principal: Principal, answer: str) -> tuple[str, list[str]]:
    """Return (safe_answer, findings). Non-empty findings means something was caught.

    Order of severity: RBAC leak → refuse the whole answer; a disallowed link →
    strip it in place, and if an obfuscated form survives, refuse the answer.
    All matching is done on a canonicalised copy so Unicode/obfuscation evasion
    (full-width, zero-width, homoglyph, ``hxxp://evil[.]com``) doesn't slip past.
    """
    clean = strip_invisibles(answer or "")

    findings = scan(principal.role, clean)
    if findings:
        return _REFUSAL, findings

    bad_hosts = scan_links(clean)
    if bad_hosts:
        stripped = strip_links(clean)
        # If a bad host still survives after surgical removal, it was obfuscated
        # past the URL regex — fall back to a safe, link-free reply.
        if scan_links(stripped):
            stripped = _LINK_REFUSAL
        return stripped, [f"external_link:{h}" for h in bad_hosts]

    return clean, []
