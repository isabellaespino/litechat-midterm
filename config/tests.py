import re

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


class ContrastTests(TestCase):
    """Every text/background pair in the navy-and-gold palette meets WCAG AA (4.5:1)."""

    # (text token, background token) pairs actually used by the CSS.
    PAIRS = [
        ("text", "page"), ("text", "card"), ("muted", "page"), ("muted", "card"),
        ("navy-700", "card"), ("navy-700", "page"),  # links
        ("on-navy", "navy-900"), ("on-navy", "navy-800"), ("on-navy", "navy-700"),
        ("muted-on-navy", "navy-900"), ("muted-on-navy", "navy-800"), ("muted-on-navy", "navy-700"),
        ("gold", "navy-900"), ("gold", "navy-800"),  # nav balance, mobile "Chats"
        ("navy-900", "gold"), ("navy-900", "gold-hover"),  # button text
        ("text", "navy-100"), ("muted", "navy-100"), ("text", "gold-soft"),
        ("error", "card"), ("error", "error-soft"), ("on-navy", "error"),
    ]

    @classmethod
    def tokens(cls):
        from pathlib import Path

        from django.conf import settings

        css = Path(settings.BASE_DIR, "templates/base.html").read_text()
        root = re.search(r":root\s*\{(.*?)\}", css, re.S).group(1)
        return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", root)), css

    @staticmethod
    def ratio(fg, bg):
        def luminance(hex_color):
            channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        light, dark = sorted([luminance(fg), luminance(bg)], reverse=True)
        return (light + 0.05) / (dark + 0.05)

    def test_every_pair_meets_aa(self):
        tokens, _ = self.tokens()
        for fg, bg in self.PAIRS:
            with self.subTest(pair=f"{fg} on {bg}"):
                self.assertGreaterEqual(self.ratio(tokens[fg], tokens[bg]), 4.5)

    def test_gold_text_only_on_navy(self):
        # Gold is ~1.9:1 on white, so it may only be a text color where the background is navy.
        _, css = self.tokens()
        selectors = [
            rule.strip()
            for rule, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
            if re.search(r"(?<![-\w])color:\s*var\(--gold\)", body)
        ]
        allowed = {"nav .credit", ".mobile-chats summary"}
        for selector in selectors:
            with self.subTest(selector=selector):
                self.assertTrue(selector in allowed or selector.startswith("body.landing .hero"), selector)


class EstimateTests(TestCase):
    def model(self, input_price, output_price):
        from catalog.models import LLMModel

        return LLMModel(input_price_micros_per_mtok=input_price, output_price_micros_per_mtok=output_price)

    def test_seeded_prices(self):
        from catalog.estimates import estimate_messages

        budget = 2_000_000
        self.assertEqual(estimate_messages(self.model(1_000_000, 5_000_000), budget), (2_000, 1_000))  # Claude
        self.assertEqual(estimate_messages(self.model(300_000, 2_500_000), budget), (900, 2_222))  # Gemini
        self.assertEqual(estimate_messages(self.model(500_000, 2_000_000), budget), (850, 2_352))  # GPT

    def test_rounds_up_like_real_charges_and_handles_free(self):
        from catalog.estimates import estimate_messages

        self.assertEqual(estimate_messages(self.model(1, 0), 2_000_000), (1, 2_000_000))  # 0.0005 µ$ -> 1
        self.assertEqual(estimate_messages(self.model(0, 0), 2_000_000), (0, None))


class LandingPageTests(TestCase):
    def setUp(self):
        from django.core.management import call_command

        call_command("seed", stdout=open("/dev/null", "w"))

    def test_hero(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<h1>Your everyday hero for AI.</h1>", html=True)
        self.assertContains(response, "Chat4All gives everyone access to top AI models, with no subscription")
        self.assertContains(response, '<svg class="emblem"')
        self.assertContains(response, 'role="img" aria-label="Chat4All emblem"')
        self.assertNotContains(response, "<img")
        self.assertContains(response, f'<a class="btn cta" href="{reverse("signup")}">Get started</a>', html=True)

    def test_logged_in_cta_starts_a_chat(self):
        self.client.force_login(User.objects.create_user("alice", password="pw-12345-long"))
        response = self.client.get(reverse("home"))
        self.assertContains(response, f'<a class="btn cta" href="{reverse("chat_new")}">Start a chat</a>', html=True)
        self.assertNotContains(response, ">Get started<")

    def test_how_it_works(self):
        html = self.client.get(reverse("home")).content.decode()
        steps = re.findall(r'<li class="step">.*?<h3>(.*?)</h3>', html, re.S)
        self.assertEqual(
            steps,
            [
                "Sign up and get $2.00 free",
                "Pick a model from OpenAI, Anthropic or Google",
                "Pay only for each reply",
            ],
        )
        self.assertIn("fraction of a cent", html)

    def snapshot_rows(self):
        html = self.client.get(reverse("home")).content.decode()
        body = html.split('<table class="snapshot">')[1].split("</table>")[0]
        rows = re.findall(r"<tr>(.*?)</tr>", body.split("<tbody>")[1], re.S)
        return html, [
            (
                re.search(r"<strong>(.*?)</strong>", row).group(1),
                re.findall(r'class="num">(?:<strong>)?([^<]+)', row),
            )
            for row in rows
        ]

    def test_price_snapshot_from_catalog(self):
        html, rows = self.snapshot_rows()
        self.assertEqual(
            rows,
            [
                ("Claude Haiku", ["$0.002", "1,000"]),
                ("Gemini Flash", ["$0.0009", "2,222"]),
                ("GPT-5.6 Luna", ["$0.00085", "2,352"]),
            ],
        )
        self.assertIn("≈ messages for $2.00 (estimate)", html)
        self.assertIn("These are estimates", html)
        self.assertIn("500 input tokens", html)
        self.assertIn("300-token reply", html)

    def test_snapshot_follows_catalog_changes(self):
        from catalog.models import LLMModel

        LLMModel.objects.filter(api_model_id="gemini-3.8-flash").update(is_active=False)
        LLMModel.objects.filter(api_model_id="gpt-5.6-luna").update(output_price_micros_per_mtok=4_000_000)
        LLMModel.objects.filter(api_model_id="claude-haiku-4-5-20251001").update(
            input_price_micros_per_mtok=0, output_price_micros_per_mtok=0
        )
        _, rows = self.snapshot_rows()
        self.assertEqual(
            rows,
            [
                ("Claude Haiku", ["—", "—"]),  # free: no division by zero
                ("GPT-5.6 Luna", ["$0.00145", "1,379"]),  # 250 + 1,200 µ$
            ],
        )

    def test_hero_theme_only_on_landing(self):
        from catalog.models import LLMModel
        from chat.models import Conversation

        self.assertContains(self.client.get(reverse("home")), '<body class="landing">')
        user = User.objects.create_user("alice", password="pw-12345-long")
        conversation = Conversation.objects.create(owner=user, llm_model=LLMModel.objects.first())
        pages = [reverse("model_list"), reverse("login"), reverse("signup")]
        for url in pages:
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertNotIn('class="landing"', html)
                self.assertNotIn("<svg", html)
        self.client.force_login(user)
        for url in [reverse("chat_detail", args=[conversation.pk]), reverse("profile")]:
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertNotIn('class="landing"', html)
                self.assertNotIn("<svg", html)
