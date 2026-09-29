"""Google Gemini generateContent through the LLM proxy."""

from urllib.parse import quote

from django.conf import settings

from .base import LLMReply
from .http import estimated_usage, malformed, post_json, require_key

PROVIDER = "Google"
ROLES = {"user": "user", "assistant": "model"}
STOP_REASONS = {"STOP": "stop", "MAX_TOKENS": "length", "SAFETY": "safety"}


def complete(api_model_id, messages, system=None):
    api_key = require_key(settings.GOOGLE_API_KEY, "GOOGLE_API_KEY")
    body = {
        "contents": [
            {"role": ROLES[m["role"]], "parts": [{"text": m["content"]}]} for m in messages
        ],
        "generationConfig": {
            "maxOutputTokens": settings.MAX_OUTPUT_TOKENS,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    data = post_json(
        PROVIDER,
        api_model_id,
        f"{settings.LLM_PROXY_BASE_URL}/google/v1beta/models/"
        f"{quote(api_model_id, safe='')}:generateContent",
        {"x-goog-api-key": api_key, "Content-Type": "application/json"},
        body,
    )
    try:
        candidate = data["candidates"][0]
        raw_stop = candidate.get("finishReason") or ""
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if parts is None:
            # A reply blocked by the safety filter can come back with no text at all.
            # That's a valid (charged) reply, not an error.
            if raw_stop != "SAFETY":
                raise KeyError("candidate has no content")
            text = ""
        else:
            if not isinstance(parts, list):
                raise TypeError("parts is not a list")
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    except (KeyError, IndexError, TypeError, AttributeError):
        raise malformed(PROVIDER, api_model_id) from None

    stop_reason = STOP_REASONS.get(raw_stop, raw_stop.lower())
    usage = data.get("usageMetadata") or {}
    input_tokens = usage.get("promptTokenCount")
    if isinstance(input_tokens, int):
        # Gemini omits candidatesTokenCount when it's 0, and bills thinking tokens as output.
        output_tokens = (usage.get("candidatesTokenCount") or 0) + (usage.get("thoughtsTokenCount") or 0)
        return LLMReply(text, input_tokens, output_tokens, stop_reason)

    prompt = ([system] if system else []) + [m["content"] for m in messages]
    input_tokens, output_tokens = estimated_usage(PROVIDER, api_model_id, prompt, text)
    return LLMReply(text, input_tokens, output_tokens, stop_reason, usage_estimated=True)
