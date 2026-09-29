from django.db import models


class LLMModel(models.Model):
    class Provider(models.TextChoices):
        OPENAI = "openai", "OpenAI"
        ANTHROPIC = "anthropic", "Anthropic"
        GOOGLE = "google", "Google"

    class Tier(models.TextChoices):
        VALUE = "value", "Value"
        STANDARD = "standard", "Standard"
        PREMIUM = "premium", "Premium"

    provider = models.CharField(max_length=20, choices=Provider.choices)
    api_model_id = models.CharField(
        "API model id",
        max_length=100,
        unique=True,
        help_text="The model id sent to the proxy, e.g. gpt-5.6-luna.",
    )
    display_name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    tier = models.CharField(max_length=20, choices=Tier.choices, default=Tier.STANDARD)
    input_price_micros_per_mtok = models.PositiveBigIntegerField(
        "input price (µ$ per 1M tokens)"
    )
    output_price_micros_per_mtok = models.PositiveBigIntegerField(
        "output price (µ$ per 1M tokens)"
    )
    is_active = models.BooleanField("active", default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["provider", "sort_order", "display_name"]
        verbose_name = "LLM model"

    def __str__(self):
        return f"{self.get_provider_display()} · {self.display_name}"
