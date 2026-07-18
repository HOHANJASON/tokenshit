# Features

## Tool calling (function calling)

Models flagged with tool-calling support accept the OpenAI `tools=[...]`
parameter and return `tool_calls` in the response. The gateway forwards the
tools schema to the upstream model unchanged, so agent frameworks
(LangChain, LangGraph, the OpenAI SDK tool runner) work out of the box.

## Streaming

Pass `stream: true` to receive server-sent events chunk by chunk, exactly
like the OpenAI API. Recommended for chat interfaces.

## Embeddings and other endpoints

Besides chat completions, the gateway proxies embeddings, moderations and
image endpoints where the underlying model supports them. Check the model's
`endpoint_type` on the Models page.

## Observability

Every call is logged with tokens, cost, latency and status. Customers see
their own calls; use the dashboard or ask this copilot for a summary.
