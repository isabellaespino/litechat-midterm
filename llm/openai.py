"""OpenAI Chat Completions through the LLM proxy."""

import logging
import math

import requests
from django.conf import settings

from . import LLMError, LLMReply

logger = logging.getLogger(__name__)

UNAVAILABLE = "The model is busy or unavailable right now. Please try again in a moment."
FAILED = "The model couldn't answer that request. Please try again."


def estimate_tokens(text):
    return math.ceil(len(text) / 4)


def complete(api_model_id, messages):
    api_key = settings.OPENAI_API_KEY
    if not api_key:
        logger.error("OPENAI_API_KEY is not set")
        raise LLMError(503, UNAVAILABLE)

    url = f"{settings.LLM_PROXY_BASE_URL}/openai/v1/chat/completions"
    body = {
        "model": api_model_id,
        "messages": messages,
        "max_tokens": settings.MAX_OUTPUT_TOKENS,
        "reasoning_effort": "none",
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(
            url, json=body, headers=headers, timeout=settings.LLM_TIMEOUT_SECONDS
        )
    except (requests.Timeout, requests.ConnectionError) as exc:
        logger.warning("OpenAI proxy unreachable for %s: %s", api_model_id, type(exc).__name__)
        raise LLMError(503, UNAVAILABLE) from None

    if response.status_code in (429, 503):
        logger.warning("OpenAI proxy returned %s for %s", response.status_code, api_model_id)
        raise LLMError(503, UNAVAILABLE)
    if not 200 <= response.status_code < 300:
        logger.error("OpenAI proxy returned %s for %s", response.status_code, api_model_id)
        raise LLMError(502, FAILED)

    try:
        data = response.json()
        choice = data["choices"][0]
        text = choice["message"]["content"]
        if not isinstance(text, str):
            raise TypeError("content is not a string")
    except (ValueError, KeyError, IndexError, TypeError):
        logger.error("OpenAI proxy sent a malformed response for %s", api_model_id)
        raise LLMError(502, FAILED) from None

    stop_reason = choice.get("finish_reason") or ""
    usage = data.get("usage") or {}
    input_tokens = usage.get("prompt_tokens")
    output_tokens = usage.get("completion_tokens")
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        return LLMReply(text, input_tokens, output_tokens, stop_reason)

    logger.warning("OpenAI proxy omitted usage for %s; estimating tokens", api_model_id)
    return LLMReply(
        text,
        estimate_tokens("".join(m["content"] for m in messages)),
        estimate_tokens(text),
        stop_reason,
        usage_estimated=True,
    )
