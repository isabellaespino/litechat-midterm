import re
from unittest import mock

from django.contrib.auth.models import User
from django.db.models import Sum
from django.test import TestCase, override_settings
from django.urls import reverse

from billing.models import CreditTransaction, Wallet
from billing.services import reply_cost_micros
from catalog.models import LLMModel
from llm import LLMError, LLMReply

from .models import Conversation, Message
from .services import send_message, title_from

PASSWORD = "correct-horse-battery-9"


def make_gpt(**overrides):
    fields = dict(
        provider="openai",
        api_model_id="gpt-5.6-luna",
        display_name="GPT-5.6 Luna",
        tier="value",
        input_price_micros_per_mtok=500_000,
        output_price_micros_per_mtok=2_000_000,
    )
    fields.update(overrides)
    return LLMModel.objects.create(**fields)


class CostAndTitleTests(TestCase):
    def test_reply_cost(self):
        self.assertEqual(reply_cost_micros(1000, 300, 500_000, 2_000_000), 1_100)
        self.assertEqual(reply_cost_micros(1, 0, 300_000, 2_500_000), 1)  # 0.3 µ$ rounds up
        self.assertEqual(reply_cost_micros(0, 0, 500_000, 2_000_000), 0)

    def test_title_from(self):
        self.assertEqual(title_from("  Plan a   trip\nto Rome  "), "Plan a trip")
        long = "word " * 30
        title = title_from(long)
        self.assertEqual(len(title), 50)
        self.assertTrue(title.endswith("…"))
        self.assertEqual(title_from("   \n  "), "New chat")


@mock.patch("llm.complete")
class SendMessageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password=PASSWORD)
        self.gpt = make_gpt()

    def reply(self, text="Hello!", input_tokens=1000, output_tokens=300):
        return LLMReply(text, input_tokens, output_tokens, "stop")

    def test_saves_messages_and_charges_exact_cost(self, complete):
        complete.return_value = self.reply()
        conversation = send_message(self.user, self.gpt, "Hi there")

        self.assertEqual(conversation.title, "Hi there")
        user_msg, assistant = conversation.messages.all()
        self.assertEqual((user_msg.role, user_msg.content), ("user", "Hi there"))
        self.assertEqual(assistant.role, "assistant")
        self.assertEqual(assistant.cost_micros, 1_100)
        self.assertEqual(assistant.input_price_micros_per_mtok, 500_000)

        charge = CreditTransaction.objects.get(user=self.user, kind="charge")
        self.assertEqual(charge.amount_micros, -1_100)
        self.assertEqual(charge.message, assistant)
        wallet = Wallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance_micros, 2_000_000 - 1_100)
        total = CreditTransaction.objects.filter(user=self.user).aggregate(t=Sum("amount_micros"))["t"]
        self.assertEqual(wallet.balance_micros, total)

    def test_failure_saves_and_charges_nothing(self, complete):
        complete.side_effect = LLMError(502, "nope")
        with self.assertRaises(LLMError):
            send_message(self.user, self.gpt, "Hi there")
        self.assertEqual(Conversation.objects.count(), 0)
        self.assertEqual(Message.objects.count(), 0)
        self.assertFalse(CreditTransaction.objects.filter(kind="charge").exists())
        self.assertEqual(Wallet.objects.get(user=self.user).balance_micros, 2_000_000)

    def test_history_is_resent_in_order(self, complete):
        complete.return_value = self.reply("A1")
        conversation = send_message(self.user, self.gpt, "Q1")
        complete.return_value = self.reply("A2")
        send_message(self.user, self.gpt, "Q2", conversation)
        complete.return_value = self.reply("A3")
        send_message(self.user, self.gpt, "Q3", conversation)

        sent = complete.call_args.args[1]
        self.assertEqual(
            sent,
            [
                {"role": "user", "content": "Q1"},
                {"role": "assistant", "content": "A1"},
                {"role": "user", "content": "Q2"},
                {"role": "assistant", "content": "A2"},
                {"role": "user", "content": "Q3"},
            ],
        )
        self.assertEqual(conversation.messages.count(), 6)
        self.assertEqual(CreditTransaction.objects.filter(kind="charge").count(), 3)

    def test_charge_may_take_balance_negative(self, complete):
        Wallet.objects.filter(user=self.user).update(balance_micros=1)
        complete.return_value = self.reply()
        send_message(self.user, self.gpt, "Hi")
        self.assertEqual(Wallet.objects.get(user=self.user).balance_micros, 1 - 1_100)


@mock.patch("llm.complete")
class ChatAdminTests(TestCase):
    def test_conversation_and_charge_pages_show_dollars(self, complete):
        from django.urls import reverse

        user = User.objects.create_user("alice", password=PASSWORD)
        complete.return_value = LLMReply("Hello!", 1000, 300, "stop")
        conversation = send_message(user, make_gpt(), "Hi there")
        admin = User.objects.create_superuser("root", password=PASSWORD)
        self.client.force_login(admin)

        page = self.client.get(reverse("admin:chat_conversation_change", args=[conversation.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "$0.0011")

        ledger = self.client.get(reverse("admin:billing_credittransaction_changelist"))
        self.assertContains(ledger, "-$0.0011")
        self.assertContains(ledger, "Hi there")
        self.assertEqual(
            self.client.get(reverse("admin:chat_conversation_add")).status_code, 403
        )


def main_region(response):
    """The page below the top nav (sidebar + chat), where no costs may appear."""
    content = response.content.decode()
    return content[content.index("<main"):]


def proxy_ok(content="Hello! How can I help?", prompt_tokens=1000, completion_tokens=300, finish_reason="stop"):
    response = mock.Mock(status_code=200)
    response.json.return_value = {
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
    return response


def proxy_status(status):
    response = mock.Mock(status_code=status)
    response.json.return_value = {"error": {"message": "upstream says no"}}
    return response


@override_settings(OPENAI_API_KEY="test-key")
@mock.patch("llm.openai.requests.post")
class ChatViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password=PASSWORD)
        self.gpt = make_gpt()
        self.claude = make_gpt(
            provider="anthropic",
            api_model_id="claude-haiku-4-5-20251001",
            display_name="Claude Haiku",
            input_price_micros_per_mtok=1_000_000,
            output_price_micros_per_mtok=5_000_000,
        )
        self.client.force_login(self.user)

    def balance(self):
        return Wallet.objects.get(user=self.user).balance_micros

    def set_balance(self, micros):
        Wallet.objects.filter(user=self.user).update(balance_micros=micros)

    def start_chat(self, content="Hi there", model=None):
        return self.client.post(
            reverse("chat_new"), {"llm_model": (model or self.gpt).pk, "content": content}
        )

    def test_anonymous_is_redirected(self, post):
        self.client.logout()
        conversation = Conversation.objects.create(owner=self.user, llm_model=self.gpt)
        for url in (reverse("chat_list"), reverse("chat_new"), reverse("chat_detail", args=[conversation.pk])):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(reverse("login")))

    def test_new_chat_page_lists_only_chat_models(self, post):
        response = self.client.get(reverse("chat_new"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GPT-5.6 Luna")
        self.assertContains(response, '<optgroup label="OpenAI">')
        self.assertNotContains(response, "Claude Haiku")

    def test_start_chat_charges_and_redirects(self, post):
        post.return_value = proxy_ok()
        response = self.start_chat()

        conversation = Conversation.objects.get()
        self.assertRedirects(
            response, reverse("chat_detail", args=[conversation.pk]) + "#latest",
            fetch_redirect_response=False,
        )
        self.assertEqual(conversation.messages.count(), 2)
        self.assertEqual(self.balance(), 2_000_000 - 1_100)
        charge = CreditTransaction.objects.get(kind="charge")
        self.assertEqual(charge.message, conversation.messages.last())
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 1024)

        page = self.client.get(reverse("chat_detail", args=[conversation.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Hello! How can I help?")

    def test_second_send_resends_history(self, post):
        post.return_value = proxy_ok("A1")
        self.start_chat("Q1")
        conversation = Conversation.objects.get()
        post.return_value = proxy_ok("A2")
        response = self.client.post(reverse("chat_detail", args=[conversation.pk]), {"content": "Q2"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            post.call_args.kwargs["json"]["messages"],
            [
                {"role": "user", "content": "Q1"},
                {"role": "assistant", "content": "A1"},
                {"role": "user", "content": "Q2"},
            ],
        )
        self.assertEqual(CreditTransaction.objects.filter(kind="charge").count(), 2)
        self.assertEqual(self.balance(), 2_000_000 - 2 * 1_100)

    def test_proxy_failures_save_and_charge_nothing(self, post):
        import requests

        cases = [
            (proxy_status(500), None, 502),
            (proxy_status(429), None, 503),
            (None, requests.Timeout(), 503),
        ]
        for return_value, side_effect, expected in cases:
            with self.subTest(expected=expected, side_effect=side_effect):
                post.return_value, post.side_effect = return_value, side_effect
                response = self.start_chat("My unsent draft")
                self.assertEqual(response.status_code, expected)
                self.assertContains(response, "My unsent draft", status_code=expected)
                self.assertNotContains(response, "upstream says no", status_code=expected)
                self.assertEqual(Conversation.objects.count(), 0)
                self.assertEqual(Message.objects.count(), 0)
                self.assertEqual(self.balance(), 2_000_000)

    def test_proxy_failure_in_existing_chat(self, post):
        post.return_value = proxy_ok()
        self.start_chat()
        conversation = Conversation.objects.get()
        post.return_value = proxy_status(502)
        response = self.client.post(reverse("chat_detail", args=[conversation.pk]), {"content": "Follow-up draft"})
        self.assertEqual(response.status_code, 502)
        self.assertContains(response, "Follow-up draft", status_code=502)
        self.assertEqual(conversation.messages.count(), 2)
        self.assertEqual(self.balance(), 2_000_000 - 1_100)

    def test_blocked_at_zero_or_less(self, post):
        post.return_value = proxy_ok()
        self.start_chat()
        conversation = Conversation.objects.get()
        post.reset_mock()
        for balance in (0, -1):
            with self.subTest(balance=balance):
                self.set_balance(balance)
                response = self.start_chat()
                self.assertEqual(response.status_code, 402)
                self.assertContains(response, "out of credit", status_code=402)
                response = self.client.post(reverse("chat_detail", args=[conversation.pk]), {"content": "More"})
                self.assertEqual(response.status_code, 402)
        post.assert_not_called()
        self.assertEqual(Conversation.objects.count(), 1)

    def test_last_reply_can_go_slightly_negative(self, post):
        self.set_balance(1)
        post.return_value = proxy_ok()
        self.assertEqual(self.start_chat().status_code, 302)
        self.assertEqual(self.balance(), 1 - 1_100)
        self.assertEqual(self.start_chat().status_code, 402)
        page = self.client.get(reverse("home"))
        self.assertContains(page, "<span data-nav-balance>-$0.01</span>", html=True)

    def test_invalid_input_is_400_without_proxy_call(self, post):
        too_long = "x" * 8001
        self.assertEqual(self.start_chat("").status_code, 400)
        self.assertEqual(self.start_chat(too_long).status_code, 400)
        self.assertEqual(self.start_chat(model=self.claude).status_code, 400)
        response = self.client.post(reverse("chat_new"), {"content": "Hi"})
        self.assertEqual(response.status_code, 400)

        conversation = Conversation.objects.create(owner=self.user, llm_model=self.gpt)
        url = reverse("chat_detail", args=[conversation.pk])
        self.assertEqual(self.client.post(url, {"content": "  "}).status_code, 400)
        LLMModel.objects.filter(pk=self.gpt.pk).update(is_active=False)
        response = self.client.post(url, {"content": "Hi"})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "no longer available", status_code=400)
        post.assert_not_called()

    def test_other_users_chat_is_404(self, post):
        bob = User.objects.create_user("bob", password=PASSWORD)
        conversation = Conversation.objects.create(owner=bob, llm_model=self.gpt, title="Bob's secret")
        url = reverse("chat_detail", args=[conversation.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {"content": "Hi"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("chat_detail", args=[99999])).status_code, 404)
        post.assert_not_called()

    def test_chats_url_redirects_to_latest_chat(self, post):
        self.assertRedirects(self.client.get(reverse("chat_list")), reverse("chat_new"))
        post.return_value = proxy_ok()
        self.start_chat("Older chat")
        self.start_chat("Newer chat")
        newest = Conversation.objects.get(title="Newer chat")
        self.assertRedirects(
            self.client.get(reverse("chat_list")), reverse("chat_detail", args=[newest.pk])
        )

    def test_sidebar_lists_own_chats_newest_first(self, post):
        bob = User.objects.create_user("bob", password=PASSWORD)
        Conversation.objects.create(owner=bob, llm_model=self.gpt, title="Bob chat")
        post.return_value = proxy_ok()
        self.start_chat("Older chat")
        self.start_chat("Newer chat")
        older = Conversation.objects.get(title="Older chat")

        response = self.client.get(reverse("chat_detail", args=[older.pk]))
        sidebar = main_region(response).split('<section class="chat-main">')[0]
        self.assertLess(sidebar.index("Newer chat"), sidebar.index("Older chat"))
        self.assertNotIn("Bob chat", sidebar)
        self.assertIn(
            f'<a href="{reverse("chat_detail", args=[older.pk])}" aria-current="page">Older chat</a>',
            sidebar,
        )
        self.assertIn(f'href="{reverse("chat_new")}">+ New chat', sidebar)
        self.assertContains(response, f'href="{reverse("chat_list")}">Chats</a>')

    def test_bubbles_in_order(self, post):
        post.return_value = proxy_ok("A1")
        self.start_chat("Q1")
        conversation = Conversation.objects.get()
        post.return_value = proxy_ok("A2")
        self.client.post(reverse("chat_detail", args=[conversation.pk]), {"content": "Q2"})
        region = main_region(self.client.get(reverse("chat_detail", args=[conversation.pk])))
        thread = region.split('class="thread-inner"')[1]
        bubbles = re.findall(r'class="bubble (user|assistant)"', thread)
        self.assertEqual(bubbles, ["user", "assistant", "user", "assistant"])
        self.assertLess(thread.index("Q1"), thread.index("A1"))
        self.assertLess(thread.index("A1"), thread.index("Q2"))

    def test_no_costs_or_tokens_on_chat_pages(self, post):
        post.return_value = proxy_ok()
        self.start_chat()
        conversation = Conversation.objects.get()
        for url in (reverse("chat_detail", args=[conversation.pk]), reverse("chat_new")):
            with self.subTest(url=url):
                response = self.client.get(url)
                region = main_region(response)
                for text in ("tokens", "per 1M", "$0.0011", "$0.50", "$"):
                    self.assertNotIn(text, region)
                self.assertContains(response, "My Profile · ")

    def test_composer_picker_and_model_label(self, post):
        new = main_region(self.client.get(reverse("chat_new")))
        self.assertIn('<select name="llm_model"', new)
        self.assertIn('<optgroup label="OpenAI">', new)
        self.assertIn("GPT-5.6 Luna · Value", new)

        conversation = Conversation.objects.create(owner=self.user, llm_model=self.gpt)
        existing = main_region(self.client.get(reverse("chat_detail", args=[conversation.pk])))
        self.assertNotIn("<select", existing)
        self.assertIn('<span class="model-chip" title="Model for this chat">GPT-5.6 Luna</span>', existing)

    def test_out_of_credit_disables_composer(self, post):
        conversation = Conversation.objects.create(owner=self.user, llm_model=self.gpt)
        self.set_balance(0)
        for url in (reverse("chat_new"), reverse("chat_detail", args=[conversation.pk])):
            with self.subTest(url=url):
                region = main_region(self.client.get(url))
                self.assertIn("You're out of credit", region)
                self.assertIn(f'href="{reverse("profile")}"', region)
                self.assertRegex(region, r"<textarea[^>]* disabled>")
                self.assertRegex(region, r'<button type="submit" class="btn" disabled>')
        post.assert_not_called()

    def test_cut_off_reply_is_charged_and_flagged(self, post):
        post.return_value = proxy_ok(completion_tokens=1024, finish_reason="length")
        self.start_chat()
        conversation = Conversation.objects.get()
        self.assertEqual(self.balance(), 2_000_000 - reply_cost_micros(1000, 1024, 500_000, 2_000_000))
        page = self.client.get(reverse("chat_detail", args=[conversation.pk]))
        self.assertContains(page, "Reply was cut short.")
        self.assertNotContains(page, "1,024")

    def test_reply_html_is_escaped(self, post):
        post.return_value = proxy_ok("<script>alert(1)</script>")
        self.start_chat()
        page = self.client.get(reverse("chat_detail", args=[Conversation.objects.get().pk]))
        self.assertNotContains(page, "<script>alert(1)</script>")
        self.assertContains(page, "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_models_page_marks_coming_soon(self, post):
        response = self.client.get(reverse("model_list"))
        self.assertContains(response, "Coming soon", count=1)
        self.assertContains(response, f'href="{reverse("chat_new")}">Start a chat')
