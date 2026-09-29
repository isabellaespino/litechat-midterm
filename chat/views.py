from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from billing.services import get_wallet
from llm import LLMError

from .forms import MessageForm, NewChatForm
from .models import Conversation
from .services import send_message


def has_credit(user):
    return get_wallet(user).balance_micros > 0


@login_required
def chat_list(request):
    conversations = (
        Conversation.objects.filter(owner=request.user)
        .select_related("llm_model")
        .annotate(message_count=Count("messages"), total_cost=Sum("messages__cost_micros"))
        # Meta.ordering is ignored on aggregated querysets, so order explicitly.
        .order_by("-updated_at", "-id")
    )
    return render(request, "chat/conversation_list.html", {"conversations": conversations})


@login_required
def chat_new(request):
    context = {"out_of_credit": not has_credit(request.user)}
    if request.method != "POST":
        context["form"] = NewChatForm()
        return render(request, "chat/conversation_new.html", context)

    form = NewChatForm(request.POST)
    context["form"] = form
    if not form.is_valid():
        return render(request, "chat/conversation_new.html", context, status=400)
    if not has_credit(request.user):
        return render(request, "chat/conversation_new.html", context, status=402)
    try:
        conversation = send_message(
            request.user, form.cleaned_data["llm_model"], form.cleaned_data["content"]
        )
    except LLMError as error:
        context["error"] = error.message
        return render(request, "chat/conversation_new.html", context, status=error.status)
    return redirect(reverse("chat_detail", args=[conversation.pk]) + "#latest")


@login_required
def chat_detail(request, pk):
    conversation = get_object_or_404(
        Conversation.objects.select_related("llm_model"), pk=pk, owner=request.user
    )
    model = conversation.llm_model
    context = {
        "conversation": conversation,
        "messages_list": conversation.messages.all(),
        "total_cost": conversation.messages.aggregate(t=Sum("cost_micros"))["t"] or 0,
        "model_available": model.is_active and model.provider in settings.CHAT_PROVIDERS,
        "out_of_credit": not has_credit(request.user),
    }
    if request.method != "POST":
        context["form"] = MessageForm()
        return render(request, "chat/conversation_detail.html", context)

    form = MessageForm(request.POST)
    context["form"] = form
    if not form.is_valid():
        return render(request, "chat/conversation_detail.html", context, status=400)
    if not context["model_available"]:
        context["error"] = "This model is no longer available. Start a new chat."
        return render(request, "chat/conversation_detail.html", context, status=400)
    if not has_credit(request.user):
        return render(request, "chat/conversation_detail.html", context, status=402)
    try:
        send_message(request.user, model, form.cleaned_data["content"], conversation)
    except LLMError as error:
        context["error"] = error.message
        return render(request, "chat/conversation_detail.html", context, status=error.status)
    return redirect(reverse("chat_detail", args=[conversation.pk]) + "#latest")
