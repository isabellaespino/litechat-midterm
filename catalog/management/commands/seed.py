from django.core.management.base import BaseCommand

from catalog.models import LLMModel

# The three models the LLM proxy serves. Prices are micro-dollars per 1M tokens.
SEED_MODELS = [
    {
        "api_model_id": "claude-haiku-4-5-20251001",
        "provider": LLMModel.Provider.ANTHROPIC,
        "display_name": "Claude Haiku",
        "description": "Anthropic's fast, affordable model for everyday questions and writing.",
        "tier": LLMModel.Tier.VALUE,
        "input_price_micros_per_mtok": 1_000_000,
        "output_price_micros_per_mtok": 5_000_000,
    },
    {
        "api_model_id": "gpt-5.6-luna",
        "provider": LLMModel.Provider.OPENAI,
        "display_name": "GPT-5.6 Luna",
        "description": "OpenAI's lightweight model for quick answers and drafting.",
        "tier": LLMModel.Tier.VALUE,
        "input_price_micros_per_mtok": 500_000,
        "output_price_micros_per_mtok": 2_000_000,
    },
    {
        "api_model_id": "gemini-3.8-flash",
        "provider": LLMModel.Provider.GOOGLE,
        "display_name": "Gemini Flash",
        "description": "Google's low-cost model with the cheapest input tokens.",
        "tier": LLMModel.Tier.VALUE,
        "input_price_micros_per_mtok": 300_000,
        "output_price_micros_per_mtok": 2_500_000,
    },
]


class Command(BaseCommand):
    help = (
        "Add the LLM models the proxy serves to the catalog. Safe to re-run: "
        "existing models (and any admin edits to them) are left untouched."
    )

    def handle(self, *args, **options):
        for fields in SEED_MODELS:
            fields = dict(fields)
            api_model_id = fields.pop("api_model_id")
            model, created = LLMModel.objects.get_or_create(
                api_model_id=api_model_id, defaults=fields
            )
            status = "created" if created else "exists"
            self.stdout.write(f"{status}: {model} ({api_model_id})")
