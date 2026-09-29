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


class CreditPageTests(TestCase):
    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("credit"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('credit')}")

    def test_shows_balance_and_only_own_transactions(self):
        alice = User.objects.create_user("alice", password=PASSWORD)
        bob = User.objects.create_user("bob", password=PASSWORD)
        post_transaction(bob, 1_000_000, CreditTransaction.Kind.TOPUP, note="Bob's top-up")
        self.client.force_login(alice)

        response = self.client.get(reverse("credit"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Available credit: $2.00")
        self.assertContains(response, "Sign-up credit")
        self.assertNotContains(response, "Bob&#x27;s top-up")

    def test_nav_shows_available_credit(self):
        self.client.force_login(User.objects.create_user("alice", password=PASSWORD))
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Available credit: $2.00")
