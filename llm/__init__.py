"""Backend-only clients for the LLM proxy. Browser code never calls the proxy."""

from . import anthropic, google, openai
from .base import LLMError, LLMReply

__all__ = ["LLMError", "LLMReply", "complete"]

# provider -> complete(api_model_id, messages, system=None, max_output_tokens=None, timeout=None)
PROVIDERS = {
    "openai": openai.complete,
    "anthropic": anthropic.complete,
    "google": google.complete,
}


def complete(llm_model, messages, system=None, max_output_tokens=None, timeout=None):
    """Send the conversation to `llm_model` and return its whole reply.

    `system` is the optional system prompt; with None, no system prompt is sent.
    `max_output_tokens` and `timeout` default to the reply settings (1,024 tokens,
    120 s); automatic titles pass smaller values.
    """
    adapter = PROVIDERS.get(llm_model.provider)
    if adapter is None:
        raise LLMError(503, "This model isn't available yet.")
    return adapter(
        llm_model.api_model_id,
        messages,
        system=system,
        max_output_tokens=max_output_tokens,
        timeout=timeout,
    )
