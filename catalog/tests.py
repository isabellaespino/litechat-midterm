from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .admin import LLMModelForm
from .models import LLMModel


def make_model(**overrides):
    fields = dict(
        provider=LLMModel.Provider.OPENAI,
        api_model_id="gpt-test",
        display_name="GPT Test",
        tier=LLMModel.Tier.VALUE,
        input_price_micros_per_mtok=500_000,
        output_price_micros_per_mtok=2_000_000,
    )
    fields.update(overrides)
    return LLMModel.objects.create(**fields)


class ModelListPageTests(TestCase):
    def test_groups_by_provider_and_hides_inactive(self):
        make_model()
        make_model(
            provider=LLMModel.Provider.ANTHROPIC,
            api_model_id="claude-test",
            display_name="Claude Test",
        )
        make_model(api_model_id="retired", display_name="Retired Model", is_active=False)

        response = self.client.get(reverse("model_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<h2>Anthropic</h2>", html=True)
        self.assertContains(response, "<h2>OpenAI</h2>", html=True)
        self.assertContains(response, "Claude Test")
        self.assertContains(response, "$0.50 input / $2.00 output per 1M tokens")
        self.assertNotContains(response, "Retired Model")

    def test_empty_catalog(self):
        response = self.client.get(reverse("model_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No models are available yet.")


class LLMModelAdminFormTests(TestCase):
    def form_data(self, **overrides):
        data = dict(
            provider="google",
            api_model_id="gemini-test",
            display_name="Gemini Test",
            description="",
            tier="value",
            input_price="0.30",
            output_price="2.50",
            is_active="on",
            sort_order="0",
        )
        data.update(overrides)
        return data

    def test_dollar_prices_are_stored_as_micros(self):
        form = LLMModelForm(data=self.form_data())
        self.assertTrue(form.is_valid(), form.errors)
        model = form.save()
        self.assertEqual(model.input_price_micros_per_mtok, 300_000)
        self.assertEqual(model.output_price_micros_per_mtok, 2_500_000)

    def test_edit_form_shows_prices_in_dollars(self):
        form = LLMModelForm(instance=make_model())
        self.assertEqual(form.fields["input_price"].initial, Decimal("0.5"))
        self.assertEqual(form.fields["output_price"].initial, Decimal("2"))

    def test_admin_add_and_changelist(self):
        admin = User.objects.create_superuser("admin", password="admin-pass-123")
        self.client.force_login(admin)
        response = self.client.post(
            reverse("admin:catalog_llmmodel_add"), self.form_data()
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            LLMModel.objects.get(api_model_id="gemini-test").input_price_micros_per_mtok,
            300_000,
        )
        changelist = self.client.get(reverse("admin:catalog_llmmodel_changelist"))
        self.assertEqual(changelist.status_code, 200)
        self.assertContains(changelist, "$0.30")


class SeedCommandTests(TestCase):
    def seed(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("seed", stdout=out)
        return out.getvalue()

    def test_creates_the_three_proxy_models(self):
        output = self.seed()
        self.assertEqual(output.count("created:"), 3)
        prices = {
            m.api_model_id: (m.provider, m.tier, m.input_price_micros_per_mtok, m.output_price_micros_per_mtok)
            for m in LLMModel.objects.all()
        }
        self.assertEqual(
            prices,
            {
                "claude-haiku-4-5-20251001": ("anthropic", "value", 1_000_000, 5_000_000),
                "gpt-5.6-luna": ("openai", "value", 500_000, 2_000_000),
                "gemini-3.8-flash": ("google", "value", 300_000, 2_500_000),
            },
        )

    def test_rerun_creates_nothing_and_keeps_admin_edits(self):
        self.seed()
        LLMModel.objects.filter(api_model_id="gpt-5.6-luna").update(
            input_price_micros_per_mtok=750_000
        )
        output = self.seed()
        self.assertEqual(output.count("created:"), 0)
        self.assertEqual(output.count("exists:"), 3)
        self.assertEqual(LLMModel.objects.count(), 3)
        self.assertEqual(
            LLMModel.objects.get(api_model_id="gpt-5.6-luna").input_price_micros_per_mtok,
            750_000,
        )
