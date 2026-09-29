from unittest import mock

from django.contrib.auth.models import User
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse

from .models import CreditTransaction, Wallet
from .services import post_transaction

PASSWORD = "correct-horse-battery-9"


class SignupCreditTests(TestCase):
    def assert_signup_credit(self, user):
        self.assertEqual(Wallet.objects.get(user=user).balance_micros, 2_000_000)
        txns = CreditTransaction.objects.filter(user=user)
        self.assertEqual(txns.count(), 1)
        self.assertEqual(txns.get().kind, CreditTransaction.Kind.SIGNUP)
        self.assertEqual(txns.get().amount_micros, 2_000_000)

    def test_create_user_gets_signup_credit(self):
        self.assert_signup_credit(User.objects.create_user("alice", password=PASSWORD))

    def test_create_superuser_gets_signup_credit(self):
        self.assert_signup_credit(User.objects.create_superuser("root", password=PASSWORD))

    def test_signup_view_gets_signup_credit(self):
        self.client.post(
            reverse("signup"),
            {"username": "alice", "password1": PASSWORD, "password2": PASSWORD},
        )
        self.assert_signup_credit(User.objects.get(username="alice"))

    def test_saving_existing_user_does_not_grant_again(self):
        user = User.objects.create_user("alice", password=PASSWORD)
        user.first_name = "Alice"
        user.save()
        self.assert_signup_credit(user)


class LedgerTests(TestCase):
    def test_str_shows_dollars(self):
        user = User.objects.create_user("alice", password=PASSWORD)
        topup = CreditTransaction(user=user, amount_micros=5_000_000, kind="topup")
        charge = CreditTransaction(user=user, amount_micros=-1_100, kind="charge")
        self.assertEqual(str(topup), "Top-up $5.00 for alice")
        self.assertEqual(str(charge), "Charge -$0.0011 for alice")

    def test_balance_equals_sum_of_ledger(self):
        user = User.objects.create_user("alice", password=PASSWORD)
        post_transaction(user, 5_000_000, CreditTransaction.Kind.TOPUP)
        post_transaction(user, -2_200, CreditTransaction.Kind.CHARGE)
        post_transaction(user, -7_000_000, CreditTransaction.Kind.ADJUSTMENT)

        total = CreditTransaction.objects.filter(user=user).aggregate(t=Sum("amount_micros"))["t"]
        wallet = Wallet.objects.get(user=user)
        self.assertEqual(wallet.balance_micros, total)
        self.assertEqual(wallet.balance_micros, -2_200)  # slightly negative is allowed


class AdminTopUpTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", password=PASSWORD)
        self.user = User.objects.create_user("alice", password=PASSWORD)
        self.client.force_login(self.admin)

    def top_up(self, **data):
        payload = {"user": self.user.pk, "amount": "5.00", "kind": "topup", "note": "Thanks"}
        payload.update(data)
        return self.client.post(reverse("admin:billing_credittransaction_add"), payload)

    def test_top_up_in_dollars_updates_balance_and_ledger(self):
        response = self.top_up()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Wallet.objects.get(user=self.user).balance_micros, 7_000_000)
        txn = CreditTransaction.objects.get(user=self.user, kind="topup")
        self.assertEqual(txn.amount_micros, 5_000_000)
        self.assertEqual(txn.created_by, self.admin)

    def test_admin_messages_and_titles_show_dollars(self):
        response = self.top_up(amount="5.00")
        txn = CreditTransaction.objects.get(user=self.user, kind="topup")
        page = self.client.get(response.url)  # changelist with the "was added" message
        self.assertContains(page, "Top-up $5.00 for alice")
        self.assertNotContains(page, "5000000")
        change = self.client.get(
            reverse("admin:billing_credittransaction_change", args=[txn.pk])
        )
        self.assertContains(change, "Top-up $5.00 for alice")
        self.assertNotContains(change, "5000000")
        self.assertNotContains(change, "µ$")
        index = self.client.get(reverse("admin:index"))  # Recent actions
        self.assertContains(index, "Top-up $5.00 for alice")

    def test_negative_top_up_is_rejected(self):
        response = self.top_up(amount="-1.00")
        self.assertEqual(response.status_code, 200)  # admin re-renders its own form
        self.assertFalse(CreditTransaction.objects.filter(kind="topup").exists())

    def test_negative_adjustment_is_allowed(self):
        self.top_up(amount="-0.50", kind="adjustment")
        self.assertEqual(Wallet.objects.get(user=self.user).balance_micros, 1_500_000)

    def test_signup_kind_cannot_be_chosen(self):
        self.top_up(kind="signup")
        self.assertEqual(CreditTransaction.objects.filter(user=self.user).count(), 1)

    def test_ledger_cannot_be_changed_or_deleted(self):
        txn = CreditTransaction.objects.get(user=self.user)
        change_url = reverse("admin:billing_credittransaction_change", args=[txn.pk])
        delete_url = reverse("admin:billing_credittransaction_delete", args=[txn.pk])

        self.assertEqual(self.client.get(change_url).status_code, 200)  # read-only view
        self.assertEqual(
            self.client.post(change_url, {"note": "edited"}).status_code, 403
        )
        self.assertEqual(self.client.get(delete_url).status_code, 403)
        self.assertEqual(self.client.post(delete_url, {"post": "yes"}).status_code, 403)
        txn.refresh_from_db()
        self.assertEqual(txn.note, "Sign-up credit")

    def test_wallet_admin_is_read_only(self):
        self.assertEqual(
            self.client.get(reverse("admin:billing_wallet_changelist")).status_code, 200
        )
        self.assertEqual(self.client.get(reverse("admin:billing_wallet_add")).status_code, 403)

    def test_user_admin_shows_available_credit(self):
        response = self.client.get(reverse("admin:auth_user_change", args=[self.user.pk]))
        self.assertContains(response, "$2.00")


def charge_reply(user, model, text, conversation=None, input_tokens=1000, output_tokens=300):
    """Send a message through the real service with a mocked model reply."""
    from chat.services import send_message
    from llm import LLMReply

    reply = LLMReply(f"Reply to {text}", input_tokens, output_tokens, "stop")
    with mock.patch("llm.complete", return_value=reply):
        return send_message(user, model, text, conversation)


def make_gpt():
    from catalog.models import LLMModel

    return LLMModel.objects.create(
        provider="openai",
        api_model_id="gpt-5.6-luna",
        display_name="GPT-5.6 Luna",
        tier="value",
        input_price_micros_per_mtok=500_000,
        output_price_micros_per_mtok=2_000_000,
    )


class ProfilePageTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", password=PASSWORD)
        self.gpt = make_gpt()
        self.client.force_login(self.alice)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("profile"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('profile')}")

    def test_new_user(self):
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<div class="balance">$2.00</div>', html=True)
        self.assertContains(response, "Sign-up credit")
        self.assertContains(response, "No chats yet")

    def test_usage_by_chat_and_reply(self):
        first = charge_reply(self.alice, self.gpt, "Older chat")
        charge_reply(self.alice, self.gpt, "Follow-up", first, input_tokens=2000, output_tokens=100)
        charge_reply(self.alice, self.gpt, "Newer chat")
        bob = User.objects.create_user("bob", password=PASSWORD)
        charge_reply(bob, self.gpt, "Bob chat")
        post_transaction(bob, 1_000_000, CreditTransaction.Kind.TOPUP, note="Bob's top-up")

        response = self.client.get(reverse("profile"))
        content = response.content.decode()

        self.assertLess(content.index("Newer chat"), content.index("Older chat"))
        self.assertNotIn("Bob chat", content)
        self.assertNotIn("Bob&#x27;s top-up", content)
        # Older chat: 1,100 µ$ + (2000×0.5 + 100×2) = 1,200 µ$ → $0.0023 over 2 replies.
        self.assertContains(response, "2 replies")
        self.assertContains(response, "3000 in / 400 out tokens")
        self.assertContains(response, "$0.0023")
        self.assertContains(response, "$0.0012")  # the follow-up reply
        self.assertEqual(content.count('class="reply-row"'), 3)

    def test_totals_match_ledger(self):
        charge_reply(self.alice, self.gpt, "Hi")
        post_transaction(self.alice, 5_000_000, CreditTransaction.Kind.TOPUP, note="Thanks")
        response = self.client.get(reverse("profile"))

        self.assertEqual(response.context["total_added"], 7_000_000)
        self.assertEqual(response.context["total_spent"], 1_100)
        wallet = Wallet.objects.get(user=self.alice)
        self.assertEqual(wallet.balance_micros, 7_000_000 - 1_100)
        ledger_sum = CreditTransaction.objects.filter(user=self.alice).aggregate(t=Sum("amount_micros"))["t"]
        self.assertEqual(wallet.balance_micros, ledger_sum)
        added = [t.kind for t in response.context["credit_added"]]
        self.assertEqual(sorted(added), ["signup", "topup"])
        self.assertContains(response, "Thanks")

    def test_pagination(self):
        from chat.models import Conversation

        for i in range(21):
            Conversation.objects.create(owner=self.alice, llm_model=self.gpt, title=f"Chat {i}")
        page1 = self.client.get(reverse("profile"))
        self.assertEqual(len(page1.context["page"].object_list), 20)
        self.assertContains(page1, "Older chats")
        page2 = self.client.get(reverse("profile") + "?page=2")
        self.assertEqual(len(page2.context["page"].object_list), 1)
        self.assertEqual(self.client.get(reverse("profile") + "?page=abc").status_code, 200)

    def test_query_count_does_not_grow_with_chats(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(reverse("profile"))
            return len(ctx.captured_queries)

        charge_reply(self.alice, self.gpt, "One")
        few = count_queries()
        for i in range(5):
            charge_reply(self.alice, self.gpt, f"More {i}")
        self.assertEqual(count_queries(), few)

    def test_old_credit_url_redirects_permanently(self):
        response = self.client.get("/credit/")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.url, reverse("profile"))

    def test_nav_shows_profile_with_balance(self):
        response = self.client.get(reverse("home"))
        self.assertContains(
            response,
            f'<a class="credit" href="{reverse("profile")}">My Profile · <span data-nav-balance>$2.00</span></a>',
            html=True,
        )
        for micros, shown in [(1, "$0.00"), (-1, "-$0.01")]:
            with self.subTest(micros=micros):
                Wallet.objects.filter(user=self.alice).update(balance_micros=micros)
                response = self.client.get(reverse("home"))
                self.assertContains(response, f"<span data-nav-balance>{shown}</span>", html=True)
