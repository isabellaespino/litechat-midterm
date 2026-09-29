from unittest import mock

import requests
from django.test import SimpleTestCase, override_settings

from catalog.models import LLMModel

from . import LLMError, complete
from . import openai as openai_client

MESSAGES = [
    {"role": "user", "content": "Hi"},
    {"role": "assistant", "content": "Hello!"},
    {"role": "user", "content": "Say hello in one sentence."},
]


def proxy_response(status=200, json_body=None, bad_json=False):
    response = mock.Mock(status_code=status)
    if bad_json:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = json_body
    return response


def ok_body(content="Hello! How can I help?", finish_reason="stop", usage=True):
    body = {
        "id": "chatcmpl_example",
        "object": "chat.completion",
        "model": "gpt-5.6-luna",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
    }
    if usage:
        body["usage"] = {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}
    return body


@override_settings(OPENAI_API_KEY="test-key", LLM_PROXY_BASE_URL="https://proxy.example")
@mock.patch("llm.openai.requests.post")
class OpenAIClientTests(SimpleTestCase):
    def test_request_shape(self, post):
        post.return_value = proxy_response(json_body=ok_body())
        openai_client.complete("gpt-5.6-luna", MESSAGES)

        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://proxy.example/openai/v1/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(
            kwargs["json"],
            {
                "model": "gpt-5.6-luna",
                "messages": MESSAGES,
                "max_tokens": 1024,
                "reasoning_effort": "none",
            },
        )
        self.assertEqual(kwargs["timeout"], 120)

    def test_success_is_parsed(self, post):
        post.return_value = proxy_response(json_body=ok_body())
        reply = openai_client.complete("gpt-5.6-luna", MESSAGES)
        self.assertEqual(reply.text, "Hello! How can I help?")
        self.assertEqual((reply.input_tokens, reply.output_tokens), (12, 8))
        self.assertEqual(reply.stop_reason, "stop")
        self.assertFalse(reply.usage_estimated)

    def test_length_finish_reason_passes_through(self, post):
        post.return_value = proxy_response(json_body=ok_body(finish_reason="length"))
        self.assertEqual(openai_client.complete("gpt-5.6-luna", MESSAGES).stop_reason, "length")

    def test_missing_usage_is_estimated(self, post):
        post.return_value = proxy_response(json_body=ok_body(content="12345678", usage=False))
        reply = openai_client.complete("gpt-5.6-luna", MESSAGES)
        self.assertTrue(reply.usage_estimated)
        self.assertEqual(reply.output_tokens, 2)  # 8 chars / 4
        self.assertEqual(reply.input_tokens, 9)  # ceil(34 chars / 4)

    def test_error_statuses(self, post):
        for status, expected in [
            (400, 502), (401, 502), (403, 502), (500, 502), (502, 502), (504, 502),
            (429, 503), (503, 503),
        ]:
            with self.subTest(status=status):
                post.return_value = proxy_response(status=status, json_body={"error": "x"})
                with self.assertRaises(LLMError) as ctx:
                    openai_client.complete("gpt-5.6-luna", MESSAGES)
                self.assertEqual(ctx.exception.status, expected)
                self.assertNotIn("test-key", ctx.exception.message)

    def test_network_failures_are_503(self, post):
        for exc in (requests.Timeout(), requests.ConnectionError()):
            with self.subTest(exc=type(exc).__name__):
                post.side_effect = exc
                with self.assertRaises(LLMError) as ctx:
                    openai_client.complete("gpt-5.6-luna", MESSAGES)
                self.assertEqual(ctx.exception.status, 503)

    def test_malformed_responses_are_502(self, post):
        for response in (
            proxy_response(bad_json=True),
            proxy_response(json_body={"choices": []}),
            proxy_response(json_body={"choices": [{"message": {"content": None}}]}),
        ):
            with self.subTest(response=response):
                post.return_value = response
                with self.assertRaises(LLMError) as ctx:
                    openai_client.complete("gpt-5.6-luna", MESSAGES)
                self.assertEqual(ctx.exception.status, 502)

    @override_settings(OPENAI_API_KEY="")
    def test_missing_key_is_503_without_request(self, post):
        with self.assertRaises(LLMError) as ctx:
            openai_client.complete("gpt-5.6-luna", MESSAGES)
        self.assertEqual(ctx.exception.status, 503)
        post.assert_not_called()

    def test_dispatch_by_provider(self, post):
        post.return_value = proxy_response(json_body=ok_body())
        gpt = LLMModel(provider="openai", api_model_id="gpt-5.6-luna")
        self.assertEqual(complete(gpt, MESSAGES).text, "Hello! How can I help?")

        claude = LLMModel(provider="anthropic", api_model_id="claude-haiku-4-5-20251001")
        with self.assertRaises(LLMError) as ctx:
            complete(claude, MESSAGES)
        self.assertEqual(ctx.exception.status, 503)
        post.assert_called_once()


class NoNetworkGuardTests(SimpleTestCase):
    def test_real_http_is_blocked(self):
        with self.assertRaisesMessage(RuntimeError, "Real HTTP request attempted"):
            requests.get("https://example.com")
