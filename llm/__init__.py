"""Backend-only clients for the LLM proxy. Browser code never calls the proxy."""

from . import openai
from .base import LLMError, LLMReply

__all__ = ["LLMError", "LLMReply", "complete"]

# provider -> complete(api_model_id, messages, system=None)
PROVIDERS = {
    "openai": openai.complete,
}


def complete(llm_model, messages, system=None):
    """Send the conversation to `llm_model` and return its whole reply.

    `system` is the optional system prompt; with None, no system prompt is sent.
    """
    adapter = PROVIDERS.get(llm_model.provider)
    if adapter is None:
        raise LLMError(503, "This model isn't available yet.")
    return adapter(llm_model.api_model_id, messages, system=system)
