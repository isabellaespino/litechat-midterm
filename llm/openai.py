"""OpenAI Chat Completions through the LLM proxy."""

from django.conf import settings

from .base import LLMReply
from .http import estimated_usage, malformed, post_json, require_key

PROVIDER = "OpenAI"
STOP_REASONS = {"stop": "stop", "length": "length"}


def complete(api_model_id, messages, system=None):
    api_key = require_key(settings.OPENAI_API_KEY, "OPENAI_API_KEY")
    if system:
        messages = [{"role": "system", "content": system}, *messages]

    data = post_json(
        PROVIDER,
        api_model_id,
        f"{settings.LLM_PROXY_BASE_URL}/openai/v1/chat/completions",
        {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        {
            "model": api_model_id,
            "messages": messages,
            "max_tokens": settings.MAX_OUTPUT_TOKENS,
            "reasoning_effort": "none",
        },
    )
    try:
        choice = data["choices"][0]
        text = choice["message"]["content"]
        if not isinstance(text, str):
            raise TypeError("content is not a string")
    except (KeyError, IndexError, TypeError):
        raise malformed(PROVIDER, api_model_id) from None

    raw_stop = choice.get("finish_reason") or ""
    stop_reason = STOP_REASONS.get(raw_stop, raw_stop)
    usage = data.get("usage") or {}
    input_tokens = usage.get("prompt_tokens")
    output_tokens = usage.get("completion_tokens")
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        return LLMReply(text, input_tokens, output_tokens, stop_reason)

    input_tokens, output_tokens = estimated_usage(
        PROVIDER, api_model_id, [m["content"] for m in messages], text
    )
    return LLMReply(text, input_tokens, output_tokens, stop_reason, usage_estimated=True)
