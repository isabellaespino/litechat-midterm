from unittest import mock

import requests
from django.test import SimpleTestCase, override_settings

from catalog.models import LLMModel

from . import LLMError, complete
from . import anthropic as anthropic_client
from . import openai as openai_client

MESSAGES = [
    {"role": "user", "content": "Hi"},
    {"role": "assistant", "content": "Hello!"},
    {"role": "user", "content": "Say hello in one sentence."},
]

TEST_KEYS = dict(
    OPENAI_API_KEY="test-openai-key",
    ANTHROPIC_API_KEY="test-anthropic-key",
    GOOGLE_API_KEY="test-google-key",
    LLM_PROXY_BASE_URL="https://proxy.example",
)


def proxy_response(status=200, json_body=None, bad_json=False):
    response = mock.Mock(status_code=status)
    if bad_json:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = json_body
    return response


def openai_body(content="Hello! How can I help?", finish_reason="stop", usage=True):
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


def anthropic_body(blocks=None, stop_reason="end_turn", usage=True, **usage_extra):
    body = {
        "id": "msg_example",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-4-5-20251001",
        "content": blocks if blocks is not None else [{"type": "text", "text": "Hello! How can I help?"}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
    }
    if usage:
        body["usage"] = {"input_tokens": 12, "output_tokens": 8, **usage_extra}
    return body


# One row per provider adapter. The shared tests below run for every row, so the
# 120 s timeout, the 502/503 mapping and the missing-key 503 are the same for all.
PROVIDER_CASES = [
    {
        "name": "openai",
        "complete": openai_client.complete,
        "model": "gpt-5.6-luna",
        "key_setting": "OPENAI_API_KEY",
        "ok_body": openai_body,
        "malformed_bodies": [
            {"choices": []},
            {"choices": [{"message": {"content": None}}]},
            ["not", "an", "object"],
        ],
    },
    {
        "name": "anthropic",
        "complete": anthropic_client.complete,
        "model": "claude-haiku-4-5-20251001",
        "key_setting": "ANTHROPIC_API_KEY",
        "ok_body": anthropic_body,
        "malformed_bodies": [
            {"type": "message"},
            {"content": "not a list"},
            {"content": [{"type": "text"}]},
            ["not", "an", "object"],
        ],
    },
]


@override_settings(**TEST_KEYS)
@mock.patch("llm.http.requests.post")
class ProxyErrorMappingTests(SimpleTestCase):
    """Identical failure handling for every provider."""

    def test_error_statuses(self, post):
        for case in PROVIDER_CASES:
            for status, expected in [
                (400, 502), (401, 502), (403, 502), (500, 502), (502, 502), (504, 502),
                (429, 503), (503, 503),
            ]:
                with self.subTest(provider=case["name"], status=status):
                    post.return_value = proxy_response(status=status, json_body={"error": "x"})
                    with self.assertRaises(LLMError) as ctx:
                        case["complete"](case["model"], MESSAGES)
                    self.assertEqual(ctx.exception.status, expected)
                    self.assertNotIn("test-", ctx.exception.message)  # never the key

    def test_network_failures_are_503(self, post):
        for case in PROVIDER_CASES:
            for exc in (requests.Timeout(), requests.ConnectionError()):
                with self.subTest(provider=case["name"], exc=type(exc).__name__):
                    post.side_effect = exc
                    with self.assertRaises(LLMError) as ctx:
                        case["complete"](case["model"], MESSAGES)
                    self.assertEqual(ctx.exception.status, 503)
        post.side_effect = None

    def test_malformed_responses_are_502(self, post):
        for case in PROVIDER_CASES:
            for response in [proxy_response(bad_json=True)] + [
                proxy_response(json_body=b) for b in case["malformed_bodies"]
            ]:
                with self.subTest(provider=case["name"], body=str(response.json.return_value)[:40]):
                    post.return_value = response
                    with self.assertRaises(LLMError) as ctx:
                        case["complete"](case["model"], MESSAGES)
                    self.assertEqual(ctx.exception.status, 502)

    def test_timeout_is_120_seconds(self, post):
        for case in PROVIDER_CASES:
            with self.subTest(provider=case["name"]):
                post.return_value = proxy_response(json_body=case["ok_body"]())
                case["complete"](case["model"], MESSAGES)
                self.assertEqual(post.call_args.kwargs["timeout"], 120)

    def test_missing_key_is_503_without_request(self, post):
        for case in PROVIDER_CASES:
            with self.subTest(provider=case["name"]), override_settings(**{case["key_setting"]: ""}):
                with self.assertRaises(LLMError) as ctx:
                    case["complete"](case["model"], MESSAGES)
                self.assertEqual(ctx.exception.status, 503)
        post.assert_not_called()


@override_settings(**TEST_KEYS)
@mock.patch("llm.http.requests.post")
class OpenAIClientTests(SimpleTestCase):
    def test_request_shape(self, post):
        post.return_value = proxy_response(json_body=openai_body())
        openai_client.complete("gpt-5.6-luna", MESSAGES)

        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://proxy.example/openai/v1/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-openai-key")
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

    def test_system_prompt_is_first_message(self, post):
        post.return_value = proxy_response(json_body=openai_body())
        openai_client.complete("gpt-5.6-luna", MESSAGES, system="Be brief.")
        sent = post.call_args.kwargs["json"]["messages"]
        self.assertEqual(sent[0], {"role": "system", "content": "Be brief."})
        self.assertEqual(sent[1:], MESSAGES)

    def test_no_system_prompt_means_no_system_message(self, post):
        post.return_value = proxy_response(json_body=openai_body())
        openai_client.complete("gpt-5.6-luna", MESSAGES, system=None)
        roles = [m["role"] for m in post.call_args.kwargs["json"]["messages"]]
        self.assertNotIn("system", roles)

    def test_success_is_parsed(self, post):
        post.return_value = proxy_response(json_body=openai_body())
        reply = openai_client.complete("gpt-5.6-luna", MESSAGES)
        self.assertEqual(reply.text, "Hello! How can I help?")
        self.assertEqual((reply.input_tokens, reply.output_tokens), (12, 8))
        self.assertEqual(reply.stop_reason, "stop")
        self.assertFalse(reply.usage_estimated)

    def test_length_finish_reason_passes_through(self, post):
        post.return_value = proxy_response(json_body=openai_body(finish_reason="length"))
        self.assertEqual(openai_client.complete("gpt-5.6-luna", MESSAGES).stop_reason, "length")

    def test_missing_usage_is_estimated(self, post):
        post.return_value = proxy_response(json_body=openai_body(content="12345678", usage=False))
        reply = openai_client.complete("gpt-5.6-luna", MESSAGES)
        self.assertTrue(reply.usage_estimated)
        self.assertEqual(reply.output_tokens, 2)  # 8 chars / 4
        self.assertEqual(reply.input_tokens, 9)  # ceil(34 chars / 4)


@override_settings(**TEST_KEYS)
@mock.patch("llm.http.requests.post")
class AnthropicClientTests(SimpleTestCase):
    def call(self, post, body=None, messages=MESSAGES, system=None):
        post.return_value = proxy_response(json_body=body or anthropic_body())
        return anthropic_client.complete("claude-haiku-4-5-20251001", messages, system=system)

    def test_request_shape(self, post):
        self.call(post)
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://proxy.example/anthropic/v1/messages")
        self.assertEqual(kwargs["headers"]["x-api-key"], "test-anthropic-key")
        self.assertEqual(kwargs["headers"]["anthropic-version"], "2023-06-01")
        self.assertNotIn("Authorization", kwargs["headers"])
        self.assertEqual(
            kwargs["json"],
            {
                "model": "claude-haiku-4-5-20251001",
                "messages": MESSAGES,
                "max_tokens": 1024,
                "thinking": {"type": "disabled"},
            },
        )
        self.assertEqual(kwargs["timeout"], 120)

    def test_system_prompt_is_top_level_string(self, post):
        self.call(post, system="Be brief.")
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["system"], "Be brief.")
        self.assertEqual(body["messages"], MESSAGES)  # not injected as a message

    def test_no_system_prompt_means_no_system_field(self, post):
        self.call(post, system=None)
        self.assertNotIn("system", post.call_args.kwargs["json"])

    def test_text_blocks_joined_and_other_blocks_ignored(self, post):
        reply = self.call(post, anthropic_body(blocks=[
            {"type": "thinking", "thinking": "secret reasoning"},
            {"type": "text", "text": "Hello, "},
            {"type": "tool_use", "id": "t1", "name": "x", "input": {}},
            {"type": "text", "text": "world."},
        ]))
        self.assertEqual(reply.text, "Hello, world.")
        self.assertNotIn("secret", reply.text)

    def test_usage_and_stop_reasons(self, post):
        reply = self.call(post)
        self.assertEqual((reply.input_tokens, reply.output_tokens), (12, 8))
        self.assertEqual(reply.stop_reason, "stop")
        self.assertFalse(reply.usage_estimated)
        self.assertEqual(self.call(post, anthropic_body(stop_reason="max_tokens")).stop_reason, "length")
        self.assertEqual(self.call(post, anthropic_body(stop_reason="refusal")).stop_reason, "refusal")

    def test_cache_tokens_count_as_input(self, post):
        reply = self.call(post, anthropic_body(cache_creation_input_tokens=5, cache_read_input_tokens=3))
        self.assertEqual(reply.input_tokens, 12 + 5 + 3)

    def test_missing_usage_is_estimated(self, post):
        reply = self.call(post, anthropic_body(blocks=[{"type": "text", "text": "12345678"}], usage=False))
        self.assertTrue(reply.usage_estimated)
        self.assertEqual((reply.input_tokens, reply.output_tokens), (9, 2))

    def test_consecutive_same_role_messages_are_merged(self, post):
        self.call(post, messages=[
            {"role": "user", "content": "First"},
            {"role": "user", "content": "Second"},
            {"role": "assistant", "content": "Reply"},
            {"role": "user", "content": "Third"},
        ])
        self.assertEqual(
            post.call_args.kwargs["json"]["messages"],
            [
                {"role": "user", "content": "First\n\nSecond"},
                {"role": "assistant", "content": "Reply"},
                {"role": "user", "content": "Third"},
            ],
        )


@override_settings(**TEST_KEYS)
@mock.patch("llm.http.requests.post")
class DispatchTests(SimpleTestCase):
    def test_dispatch_by_provider(self, post):
        post.return_value = proxy_response(json_body=openai_body())
        gpt = LLMModel(provider="openai", api_model_id="gpt-5.6-luna")
        self.assertEqual(complete(gpt, MESSAGES).text, "Hello! How can I help?")

        post.return_value = proxy_response(json_body=anthropic_body(blocks=[{"type": "text", "text": "From Claude"}]))
        claude = LLMModel(provider="anthropic", api_model_id="claude-haiku-4-5-20251001")
        self.assertEqual(complete(claude, MESSAGES).text, "From Claude")
        self.assertTrue(post.call_args.args[0].endswith("/anthropic/v1/messages"))

        unknown = LLMModel(provider="mistral", api_model_id="some-model")
        with self.assertRaises(LLMError) as ctx:
            complete(unknown, MESSAGES)
        self.assertEqual(ctx.exception.status, 503)
        self.assertEqual(post.call_count, 2)  # the unknown provider sent nothing

    def test_system_is_passed_through(self, post):
        post.return_value = proxy_response(json_body=openai_body())
        complete(LLMModel(provider="openai", api_model_id="gpt-5.6-luna"), MESSAGES, system="Be brief.")
        self.assertEqual(post.call_args.kwargs["json"]["messages"][0]["role"], "system")


class NoNetworkGuardTests(SimpleTestCase):
    def test_real_http_is_blocked(self):
        with self.assertRaisesMessage(RuntimeError, "Real HTTP request attempted"):
            requests.get("https://example.com")
