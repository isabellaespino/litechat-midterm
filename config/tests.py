from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class HomePageTests(TestCase):
    def test_home_anonymous(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)

    def test_home_logged_in(self):
        user = User.objects.create_user("alice", password="pw-12345-long")
        self.client.force_login(user)
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)


class MoneyTests(TestCase):
    def test_format_dollars_rounds_down_to_the_cent(self):
        from config.money import format_dollars

        cases = {
            2_000_000: "$2.00",
            1_990_000: "$1.99",
            1_999_999: "$1.99",
            0: "$0.00",
            9_999: "$0.00",
            -10_000: "-$0.01",
            -1: "-$0.01",
            1_234_560_000: "$1,234.56",
        }
        for micros, expected in cases.items():
            with self.subTest(micros=micros):
                self.assertEqual(format_dollars(micros), expected)

    def test_format_dollars_precise(self):
        from config.money import format_dollars_precise

        cases = {
            300_000: "$0.30",
            2_000_000: "$2.00",
            2_200: "$0.0022",
            1: "$0.000001",
            -2_200: "-$0.0022",
        }
        for micros, expected in cases.items():
            with self.subTest(micros=micros):
                self.assertEqual(format_dollars_precise(micros), expected)

    def test_dollars_to_micros(self):
        from decimal import Decimal

        from config.money import dollars_to_micros

        self.assertEqual(dollars_to_micros(Decimal("0.30")), 300_000)
        self.assertEqual(dollars_to_micros(Decimal("5")), 5_000_000)
        self.assertEqual(dollars_to_micros(Decimal("-0.000001")), -1)
        with self.assertRaises(ValueError):
            dollars_to_micros(Decimal("0.0000001"))


class BrandTests(TestCase):
    """Users see "Chat4All" everywhere; "Litechat" only survives in the proxy URL."""

    def test_no_page_says_litechat(self):
        from django.core.management import call_command

        from catalog.models import LLMModel
        from chat.models import Conversation

        call_command("seed", stdout=open("/dev/null", "w"))
        admin = User.objects.create_superuser("root", password="pw-12345-long")
        conversation = Conversation.objects.create(
            owner=admin, llm_model=LLMModel.objects.get(api_model_id="gpt-5.6-luna")
        )
        anonymous_pages = [reverse("home"), reverse("model_list"), reverse("login"), reverse("signup")]
        for url in anonymous_pages:
            with self.subTest(url=url):
                self.assert_branded(self.client.get(url))
        self.client.force_login(admin)
        for url in [
            reverse("home"), reverse("chat_new"), reverse("chat_detail", args=[conversation.pk]),
            reverse("profile"), reverse("chat_delete", args=[conversation.pk]), reverse("admin:index"),
        ]:
            with self.subTest(url=url):
                self.assert_branded(self.client.get(url))

    def assert_branded(self, response):
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertNotIn("litechat", html.lower())
        self.assertRegex(html, r"<title>[^<]*Chat4All[^<]*</title>")

    def test_nav_brand_and_admin_header(self):
        self.assertContains(self.client.get(reverse("home")), '<a class="brand" href="/">Chat4All</a>', html=True)
        User.objects.create_superuser("root", password="pw-12345-long")
        self.client.login(username="root", password="pw-12345-long")
        self.assertContains(self.client.get(reverse("admin:index")), "Chat4All administration")

    def test_chat_script_title(self):
        from pathlib import Path

        from django.conf import settings

        script = Path(settings.BASE_DIR, "templates/chat/_script.html").read_text()
        self.assertIn('" · Chat4All"', script)
        self.assertNotIn("Litechat", script)
