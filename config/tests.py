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
