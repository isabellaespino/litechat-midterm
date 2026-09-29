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


class SystemPromptTests(TestCase):
    def setUp(self):
        from .services import get_settings

        self.get_settings = get_settings
        self.user = User.objects.create_user("alice", password=PASSWORD)
        self.client.force_login(self.user)
        self.url = reverse("system_prompt")

    def test_profile_shows_section(self):
        response = self.client.get(reverse("profile"))
        self.assertContains(response, '<h2 id="system-prompt">Global System Prompt</h2>', html=True)
        self.assertContains(response, 'name="system_prompt"')
        self.assertContains(response, f'action="{self.url}"')

    def test_save_strips_and_prefills(self):
        response = self.client.post(self.url, {"system_prompt": "  Always reply in French.  "})
        self.assertRedirects(response, reverse("profile") + "#system-prompt", fetch_redirect_response=False)
        self.assertEqual(self.get_settings(self.user).system_prompt, "Always reply in French.")
        page = self.client.get(reverse("profile"))
        self.assertContains(page, "System prompt saved.")
        self.assertContains(page, "Always reply in French.</textarea>")

    def test_empty_clears(self):
        self.client.post(self.url, {"system_prompt": "Be brief."})
        self.client.post(self.url, {"system_prompt": "   "})
        self.assertEqual(self.get_settings(self.user).system_prompt, "")
        self.assertContains(self.client.get(reverse("profile")), "System prompt cleared.")

    def test_too_long_is_400_and_not_saved(self):
        response = self.client.post(self.url, {"system_prompt": "x" * 4001})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "at most 4000 characters", status_code=400)
        self.assertContains(response, "Available credit", status_code=400)  # the full profile page
        self.assertEqual(self.get_settings(self.user).system_prompt, "")

    def test_get_is_405_and_anonymous_redirected(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.logout()
        response = self.client.post(self.url, {"system_prompt": "Hi"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("login")))

    def test_admin_shows_prompt_read_only(self):
        self.client.post(self.url, {"system_prompt": "Be brief."})
        admin = User.objects.create_superuser("root", password=PASSWORD)
        self.client.force_login(admin)
        page = self.client.get(reverse("admin:auth_user_change", args=[self.user.pk]))
        self.assertContains(page, "Global System Prompt")
        self.assertContains(page, "Be brief.")


class AuthCardTests(TestCase):
    """Log-in and sign-up are centered cards: welcome heading, labeled fields,
    one full-width button, and a link to the other page. No social login."""

    def assert_card(self, response, heading, field_ids, button, link_text, link_url, status=200):
        import re

        self.assertEqual(response.status_code, status)
        html = response.content.decode()
        self.assertIn('<div class="auth-card">', html)
        self.assertIn(f"<h1>{heading}</h1>", html)
        for field_id in field_ids:
            self.assertIn(f'<label for="{field_id}">', html)
            self.assertIn(f'id="{field_id}"', html)
        buttons = re.findall(r"<button[^>]*>", html.split('<div class="auth-card">')[1])
        self.assertEqual(buttons, ['<button type="submit" class="btn block">'])
        self.assertIn(f">{button}</button>", html)
        self.assertIn(f'<a href="{link_url}">{link_text}</a>', html)
        self.assertNotIn("google", html.lower())
        return html

    def test_login_card(self):
        html = self.assert_card(
            self.client.get(reverse("login") + "?next=/profile/"),
            "Welcome back", ["id_username", "id_password"], "Log in", "Sign up", reverse("signup"),
        )
        self.assertIn('name="next" value="/profile/"', html)
        self.assertIn('autocomplete="current-password"', html)

    def test_signup_card(self):
        html = self.assert_card(
            self.client.get(reverse("signup")),
            "Welcome to Chat4All", ["id_username", "id_password1", "id_password2"], "Create account",
            "Log in", reverse("login"),
        )
        self.assertIn("get $2.00 of free credit", html)
        self.assertIn('<label for="id_password2">Confirm password</label>', html)
        self.assertIn('autocomplete="new-password"', html)

    def test_errors_render_inside_the_card_with_400(self):
        html = self.assert_card(
            self.client.post(reverse("login"), {"username": "nobody", "password": "wrong"}),
            "Welcome back", ["id_username", "id_password"], "Log in", "Sign up", reverse("signup"), status=400,
        )
        card = html.split('<div class="auth-card">')[1]
        self.assertIn('<p class="form-error" role="alert">', card)

        html = self.assert_card(
            self.client.post(reverse("signup"), {"username": "alice", "password1": PASSWORD, "password2": "different"}),
            "Welcome to Chat4All", ["id_username", "id_password1", "id_password2"], "Create account",
            "Log in", reverse("login"), status=400,
        )
        self.assertIn('<p class="field-error" role="alert">', html.split('<div class="auth-card">')[1])
