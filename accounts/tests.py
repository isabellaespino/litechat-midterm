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


class MemoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password=PASSWORD)
        self.client.force_login(self.user)
        self.add_url = reverse("memory_add")

    def memories(self, user=None):
        from .models import Memory

        return list(Memory.objects.filter(user=user or self.user).values_list("text", flat=True))

    def test_add_and_list(self):
        response = self.client.post(self.add_url, {"text": "  I'm a student  "})
        self.assertRedirects(response, reverse("profile") + "#memories", fetch_redirect_response=False)
        self.assertEqual(self.memories(), ["I'm a student"])
        page = self.client.get(reverse("profile"))
        self.assertContains(page, "Memory added.")
        self.assertContains(page, '<span class="memory-text">I&#x27;m a student</span>', html=True)
        self.assertContains(page, "1 of 10")
        self.assertContains(page, 'aria-label="Delete memory “I&#x27;m a student”"')

    def test_validation_is_400_and_stores_nothing(self):
        from .models import Memory

        self.client.post(self.add_url, {"text": "Keep answers short"})
        for text, message in [
            ("", "This field is required."),
            ("   ", "This field is required."),
            ("x" * 201, "at most 200 characters"),
            ("keep ANSWERS short", "You already have that memory."),
        ]:
            with self.subTest(text=text[:10]):
                response = self.client.post(self.add_url, {"text": text})
                self.assertEqual(response.status_code, 400)
                self.assertContains(response, message, status_code=400)
                self.assertContains(response, "Available credit", status_code=400)  # the full profile
        self.assertEqual(self.memories(), ["Keep answers short"])

        for i in range(9):
            Memory.objects.create(user=self.user, text=f"note {i}")
        response = self.client.post(self.add_url, {"text": "an eleventh"})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "You can keep up to 10 memories. Delete one to add another.", status_code=400)
        self.assertEqual(len(self.memories()), 10)
        page = self.client.get(reverse("profile"))
        self.assertContains(page, "Delete a memory to add another.")
        self.assertNotContains(page, f'action="{self.add_url}"')

    def test_delete_is_immediate_and_owner_only(self):
        from .models import Memory

        mine = Memory.objects.create(user=self.user, text="I'm a student")
        bob = User.objects.create_user("bob", password=PASSWORD)
        theirs = Memory.objects.create(user=bob, text="Bob's note")
        self.assertEqual(self.client.get(reverse("memory_delete", args=[mine.pk])).status_code, 405)
        response = self.client.post(reverse("memory_delete", args=[mine.pk]))
        self.assertRedirects(response, reverse("profile") + "#memories", fetch_redirect_response=False)
        self.assertEqual(self.memories(), [])
        self.assertEqual(self.client.post(reverse("memory_delete", args=[theirs.pk])).status_code, 404)
        self.assertEqual(self.memories(bob), ["Bob's note"])
        self.client.logout()
        response = self.client.post(self.add_url, {"text": "x"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("login")))

    def test_system_text(self):
        from .models import Memory
        from .services import get_settings, system_text_for

        self.assertIsNone(system_text_for(self.user))
        Memory.objects.create(user=self.user, text="I'm a student")
        Memory.objects.create(user=self.user, text="keep answers short")
        memories_block = "About the user (notes they asked you to remember):\n- I'm a student\n- keep answers short"
        self.assertEqual(system_text_for(self.user), memories_block)
        row = get_settings(self.user)
        row.system_prompt = "Always reply in French."
        row.save()
        self.assertEqual(system_text_for(self.user), "Always reply in French.\n\n" + memories_block)
        Memory.objects.filter(user=self.user).delete()
        self.assertEqual(system_text_for(self.user), "Always reply in French.")

    def test_estimate_shown_only_when_something_is_sent(self):
        from django.core.management import call_command

        from .models import Memory

        call_command("seed", stdout=open("/dev/null", "w"))
        page = self.client.get(reverse("profile"))
        self.assertNotContains(page, "add about")
        spent_before = page.context["total_spent"]
        Memory.objects.create(user=self.user, text="x" * 150)
        # header (50) + newline + "- " + 150 = 203 chars -> ceil(203 / 4) = 51 tokens
        page = self.client.get(reverse("profile"))
        self.assertEqual(page.context["system_tokens"], 51)
        self.assertContains(page, "add about 51 tokens to every message")
        self.assertContains(page, "≈ $0.000051 with Claude Haiku")  # 51 x $1.00/1M
        self.assertContains(page, "≈ $0.000026 with GPT-5.6 Luna")  # 51 x $0.50/1M = 25.5 -> 26
        self.assertContains(page, "≈ $0.000016 with Gemini Flash")  # 51 x $0.30/1M = 15.3 -> 16
        self.assertEqual(page.context["total_spent"], spent_before)

    def test_admin_shows_memories_read_only(self):
        from .models import Memory

        Memory.objects.create(user=self.user, text="I'm a student")
        self.client.force_login(User.objects.create_superuser("root", password=PASSWORD))
        page = self.client.get(reverse("admin:auth_user_change", args=[self.user.pk]))
        self.assertContains(page, "Memories")
        self.assertContains(page, "I&#x27;m a student")


class SystemTextSwitchTests(TestCase):
    def test_include_memories_false_keeps_prompt_only(self):
        from .models import Memory
        from .services import get_settings, system_text_for

        user = User.objects.create_user("alice", password=PASSWORD)
        Memory.objects.create(user=user, text="I'm a student")
        self.assertIsNone(system_text_for(user, include_memories=False))  # memories only -> nothing left
        self.assertIn("I'm a student", system_text_for(user, include_memories=True))
        row = get_settings(user)
        row.system_prompt = "Always reply in French."
        row.save()
        self.assertEqual(system_text_for(user, include_memories=False), "Always reply in French.")
        self.assertEqual(
            system_text_for(user),
            "Always reply in French.\n\nAbout the user (notes they asked you to remember):\n- I'm a student",
        )
