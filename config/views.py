from django.conf import settings
from django.shortcuts import render

from catalog.estimates import ASSUMED_INPUT_TOKENS, ASSUMED_OUTPUT_TOKENS, estimate_messages
from catalog.models import LLMModel


def home(request):
    """The landing page, with a price snapshot of the active models."""
    budget = settings.SIGNUP_CREDIT_MICROS
    models = list(LLMModel.objects.filter(is_active=True))
    for model in models:
        model.per_message, messages = estimate_messages(model, budget)
        model.messages_display = f"{messages:,}" if messages is not None else "—"
    return render(
        request,
        "home.html",
        {
            "models": models,
            "budget_micros": budget,
            "assumed_input_tokens": ASSUMED_INPUT_TOKENS,
            "assumed_output_tokens": ASSUMED_OUTPUT_TOKENS,
        },
    )
