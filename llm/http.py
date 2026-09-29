"""Request and error handling shared by every provider adapter.

Keeping this in one place makes the 120 s timeout and the 502/503 mapping identical
for all providers by construction.
"""

import logging
import math

import requests
from django.conf import settings

from .base import LLMError

logger = logging.getLogger("llm")

UNAVAILABLE = "The model is busy or unavailable right now. Please try again in a moment."
FAILED = "The model couldn't answer that request. Please try again."


def require_key(value, name):
    """Fail with 503 before any request if a provider's key isn't configured."""
    if not value:
        logger.error("%s is not set", name)
        raise LLMError(503, UNAVAILABLE)
    return value


def post_json(provider, api_model_id, url, headers, body):
    """POST `body` to the proxy and return the decoded JSON, or raise LLMError.

    Logs the proxy's status and the model id, never the headers, the key or the body.
    """
    try:
        response = requests.post(
            url, json=body, headers=headers, timeout=settings.LLM_TIMEOUT_SECONDS
        )
    except (requests.Timeout, requests.ConnectionError) as exc:
        logger.warning("%s proxy unreachable for %s: %s", provider, api_model_id, type(exc).__name__)
        raise LLMError(503, UNAVAILABLE) from None

    if response.status_code in (429, 503):
        logger.warning("%s proxy returned %s for %s", provider, response.status_code, api_model_id)
        raise LLMError(503, UNAVAILABLE)
    if not 200 <= response.status_code < 300:
        logger.error("%s proxy returned %s for %s", provider, response.status_code, api_model_id)
        raise LLMError(502, FAILED)

    try:
        return response.json()
    except ValueError:
        raise malformed(provider, api_model_id) from None


def malformed(provider, api_model_id):
    logger.error("%s proxy sent a malformed response for %s", provider, api_model_id)
    return LLMError(502, FAILED)


def estimate_tokens(text):
    return math.ceil(len(text) / 4)


def estimated_usage(provider, api_model_id, prompt_texts, reply_text):
    """(input, output) token estimates when the proxy omits usage. Never free."""
    logger.warning("%s proxy omitted usage for %s; estimating tokens", provider, api_model_id)
    return estimate_tokens("".join(prompt_texts)), estimate_tokens(reply_text)
