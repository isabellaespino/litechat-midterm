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
@mock.patch("llm.openai.requests.post")
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
            self.start_chat(model=self.claude),
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
