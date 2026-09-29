"""Backend-only clients for the LLM proxy. Browser code never calls the proxy."""

from dataclasses import dataclass


@dataclass
class LLMReply:
    text: str
    input_tokens: int
    output_tokens: int
    stop_reason: str
    usage_estimated: bool = False


class LLMError(Exception):
    """A failed proxy call.

    `status` is the HTTP status our view should return (502 or 503). `message` is
    safe to show users: it never contains the API key or the proxy's response body.
    """

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def complete(llm_model, messages):
    """Send the conversation to `llm_model` and return its whole reply."""
    if llm_model.provider == "openai":
        from . import openai

        return openai.complete(llm_model.api_model_id, messages)
    raise LLMError(503, "This model isn't available yet.")
