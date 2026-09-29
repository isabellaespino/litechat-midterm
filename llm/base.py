from dataclasses import dataclass


@dataclass
class LLMReply:
    text: str
    input_tokens: int
    output_tokens: int
    # Normalized across providers: "stop", "length" (cut off at the output cap),
    # "safety" (blocked by the provider), or the provider's raw value otherwise.
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
