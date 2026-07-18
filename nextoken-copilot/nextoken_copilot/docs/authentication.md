# Authentication and API keys

## Authenticate your requests

Every API request must carry your secret key in the Authorization header:
`Authorization: Bearer nxt_live_...`. Keys are shown once at creation —
store them in a secret manager or environment variable, never in code.

## Create or revoke an API key

Manage keys from the dashboard (API Keys page). You can create several keys
(for example one per environment), label them, and revoke any key instantly.
Revoking a key does not affect your other keys or your balance.

## Key security

If a key leaks, revoke it immediately and create a new one. NexToken never
returns the raw key again after creation; the dashboard and this copilot only
show the key prefix and metadata (creation date, last used, limits).

## Per-key rate limits

Each key can have its own RPM (requests per minute) and TPM (tokens per
minute) limits. A value of 0 means the account default applies.
