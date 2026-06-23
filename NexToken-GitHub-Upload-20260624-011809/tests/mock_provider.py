import json

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse


app = FastAPI()
failing_app = FastAPI()


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": "mock-gpt", "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    if body.get("stream"):
        async def events():
            chunks = [
                {"id": "chatcmpl_stream", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"role": "assistant"}}]},
                {"id": "chatcmpl_stream", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": "NexToken stream works."}}]},
                {"id": "chatcmpl_stream", "object": "chat.completion.chunk", "choices": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}},
            ]
            for chunk in chunks:
                yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")
    return {
        "id": "chatcmpl_test",
        "object": "chat.completion",
        "model": "mock-gpt",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "NexToken proxy works."}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
    }


@app.post("/v1/images/generations")
def images():
    return {"created": 1782140000, "data": [{"b64_json": "aW1hZ2U="}]}


@failing_app.get("/v1/models")
def failing_models():
    return {"object": "list", "data": []}


@failing_app.post("/v1/chat/completions")
def failing_chat():
    return StreamingResponse(iter([b'{"error":"temporary failure"}']), status_code=503, media_type="application/json")
