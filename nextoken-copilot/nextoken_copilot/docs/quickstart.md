# Quickstart

## Make your first request

NexToken is an OpenAI-compatible gateway: any OpenAI SDK or plain HTTP client
works by changing the base URL and the API key. Endpoint:
`POST {BASE_URL}/v1/chat/completions`.

```bash
curl $NEXTOKEN_BASE_URL/v1/chat/completions \
  -H "Authorization: Bearer nxt_live_..." \
  -H "Content-Type: application/json" \
  -d '{"model": "nxt-local", "messages": [{"role": "user", "content": "Hello"}]}'
```

## Use the Python SDK

Integrate with the official OpenAI Python SDK — just point it at NexToken:

```python
from openai import OpenAI
client = OpenAI(base_url=NEXTOKEN_BASE_URL + "/v1", api_key="nxt_live_...")
resp = client.chat.completions.create(model="nxt-local",
                                      messages=[{"role": "user", "content": "Hello"}])
```

## List available models

`GET /v1/models` returns the models your account can call. Pick the `id`
(for example `nxt-local`) and pass it as `model` in your requests.
