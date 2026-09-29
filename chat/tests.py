from unittest import mock

from django.contrib.auth.models import User
from django.db.models import Sum
from django.test import TestCase

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
