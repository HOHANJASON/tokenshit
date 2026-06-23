MODEL_CATALOG = [
    ("gpt-5.5", "GPT-5.5", "OpenAI", "chat"),
    ("gpt-5", "GPT-5", "OpenAI", "chat"),
    ("gpt-5-mini", "GPT-5 mini", "OpenAI", "chat"),
    ("gpt-4.1", "GPT-4.1", "OpenAI", "chat"),
    ("gpt-4.1-mini", "GPT-4.1 mini", "OpenAI", "chat"),
    ("gpt-4o", "GPT-4o", "OpenAI", "chat"),
    ("gpt-4o-mini", "GPT-4o mini", "OpenAI", "chat"),
    ("o3", "o3", "OpenAI", "chat"),
    ("o4-mini", "o4-mini", "OpenAI", "chat"),
    ("claude-opus-4-1", "Claude Opus 4.1", "Anthropic", "chat"),
    ("claude-sonnet-4", "Claude Sonnet 4", "Anthropic", "chat"),
    ("claude-3-5-haiku", "Claude Haiku 3.5", "Anthropic", "chat"),
    ("gemini-2.5-pro", "Gemini 2.5 Pro", "Google", "chat"),
    ("gemini-2.5-flash", "Gemini 2.5 Flash", "Google", "chat"),
    ("gemini-2.0-flash", "Gemini 2.0 Flash", "Google", "chat"),
    ("deepseek-chat", "DeepSeek V3", "DeepSeek", "chat"),
    ("deepseek-reasoner", "DeepSeek R1", "DeepSeek", "chat"),
    ("grok-4", "Grok 4", "xAI", "chat"),
    ("grok-3-mini", "Grok 3 mini", "xAI", "chat"),
    ("qwen3-max", "Qwen3 Max", "Alibaba", "chat"),
    ("qwen3-235b", "Qwen3 235B", "Alibaba", "chat"),
    ("qwen-plus", "Qwen Plus", "Alibaba", "chat"),
    ("qwen-turbo", "Qwen Turbo", "Alibaba", "chat"),
    ("llama-4-maverick", "Llama 4 Maverick", "Meta", "chat"),
    ("llama-4-scout", "Llama 4 Scout", "Meta", "chat"),
    ("llama-3.3-70b", "Llama 3.3 70B", "Meta", "chat"),
    ("mistral-large", "Mistral Large", "Mistral", "chat"),
    ("codestral", "Codestral", "Mistral", "chat"),
    ("gpt-image-1", "GPT Image", "OpenAI", "image"),
    ("imagen-4", "Imagen 4", "Google", "image"),
    ("flux-1.1-pro", "FLUX 1.1 Pro", "BFL", "image"),
]


def catalog_payload() -> list[dict]:
    return [
        {"id": model_id, "name": name, "vendor": vendor, "endpoint_type": endpoint_type}
        for model_id, name, vendor, endpoint_type in MODEL_CATALOG
    ]
