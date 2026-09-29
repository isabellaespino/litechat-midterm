from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

PASSWORD = "correct-horse-battery-9"


class SignUpTests(TestCase):
    url = reverse("signup")

    def test_get(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_valid_post_creates_and_logs_in(self):
        response = self.client.post(
            self.url,
            {"username": "alice", "password1": PASSWORD, "password2": PASSWORD},
        )
        self.assertRedirects(response, reverse("home"))
        user = User.objects.get(username="alice")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_mismatched_passwords_is_400(self):
        response = self.client.post(
            self.url,
            {"username": "alice", "password1": PASSWORD, "password2": PASSWORD + "x"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username="alice").exists())

    def test_duplicate_username_is_400(self):
        User.objects.create_user("alice", password=PASSWORD)
        response = self.client.post(
            self.url,
            {"username": "alice", "password1": PASSWORD, "password2": PASSWORD},
        )
        self.assertEqual(response.status_code, 400)

    def test_logged_in_user_is_redirected(self):
        self.client.force_login(User.objects.create_user("bob", password=PASSWORD))
        self.assertRedirects(self.client.get(self.url), reverse("home"))


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password=PASSWORD)

    def test_get(self):
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)

    def test_valid_credentials(self):
        response = self.client.post(
            reverse("login"), {"username": "alice", "password": PASSWORD}
        )
        self.assertRedirects(response, reverse("home"))

    def test_bad_credentials_is_400(self):
        response = self.client.post(
            reverse("login"), {"username": "alice", "password": "wrong"}
        )
        self.assertEqual(response.status_code, 400)

    def test_logged_in_user_is_redirected(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(reverse("login")), reverse("home"))

    def test_logout(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("home"))
        self.assertNotIn("_auth_user_id", self.client.session)
