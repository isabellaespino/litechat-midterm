from django.conf import settings
from django.shortcuts import render

from .models import LLMModel


def model_list(request):
    models = LLMModel.objects.filter(is_active=True)
    return render(
        request,
        "catalog/model_list.html",
        {"models": models, "chat_providers": settings.CHAT_PROVIDERS},
    )
