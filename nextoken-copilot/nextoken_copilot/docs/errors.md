# Errors and rate limits

## 401 Unauthorized

The API key is missing, malformed, or revoked. Check the Authorization
header is exactly `Bearer nxt_live_...` and that the key is still active.

## 402 Payment Required / insufficient balance

Your wallet balance is too low to cover the estimated cost of the request.
Top up your balance from the dashboard (Billing page) and retry.

## 429 Too Many Requests

You hit a rate limit: either your key's RPM (requests per minute) or TPM
(tokens per minute) limit, or the upstream provider is throttling. To fix
429 errors: slow down request bursts, add retries with exponential backoff,
or ask for a higher limit. If the response mentions `insufficient_quota`,
the upstream provider account itself is out of quota — the route will be
retried on another provider automatically when one is available.

## 5xx errors and failover

NexToken routes each model to one or more upstream providers. When a
provider fails repeatedly, its route cools down and traffic fails over to
the next active route. Transient 5xx errors are safe to retry.

## Timeouts

Long generations can take a while on smaller models. Set your client
timeout to at least 60 seconds, and prefer streaming for chat UIs.
