"""Anthropic Messages through the LLM proxy."""

from django.conf import settings

from .base import LLMReply
from .http import estimated_usage, malformed, post_json, require_key

PROVIDER = "Anthropic"
ANTHROPIC_VERSION = "2023-06-01"
STOP_REASONS = {"end_turn": "stop", "max_tokens": "length"}


def merge_same_role(messages):
    """Anthropic rejects consecutive messages with the same role; join them instead.

    Our saved history always alternates (failed sends save nothing), so this is a guard.
    """
    merged = []
    for message in messages:
        if merged and merged[-1]["role"] == message["role"]:
            merged[-1] = {
                "role": message["role"],
                "content": merged[-1]["content"] + "\n\n" + message["content"],
            }
        else:
            merged.append({"role": message["role"], "content": message["content"]})
    return merged


def complete(api_model_id, messages, system=None):
    api_key = require_key(settings.ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY")
    body = {
        "model": api_model_id,
        "messages": merge_same_role(messages),
        "max_tokens": settings.MAX_OUTPUT_TOKENS,
        "thinking": {"type": "disabled"},
    }
    if system:
        body["system"] = system

    data = post_json(
        PROVIDER,
        api_model_id,
        f"{settings.LLM_PROXY_BASE_URL}/anthropic/v1/messages",
        {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        },
        body,
    )
    try:
        blocks = data["content"]
        if not isinstance(blocks, list):
            raise TypeError("content is not a list")
        text = "".join(
            b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text"
        )
    except (KeyError, TypeError):
        raise malformed(PROVIDER, api_model_id) from None

    raw_stop = data.get("stop_reason") or ""
    stop_reason = STOP_REASONS.get(raw_stop, raw_stop)
    usage = data.get("usage") or {}
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        # We never enable prompt caching; if cache tokens ever appear, charge them as
        # input rather than give them away.
        input_tokens += (usage.get("cache_creation_input_tokens") or 0) + (
            usage.get("cache_read_input_tokens") or 0
        )
        return LLMReply(text, input_tokens, output_tokens, stop_reason)

    prompt = ([system] if system else []) + [m["content"] for m in messages]
    input_tokens, output_tokens = estimated_usage(PROVIDER, api_model_id, prompt, text)
    return LLMReply(text, input_tokens, output_tokens, stop_reason, usage_estimated=True)
