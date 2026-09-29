from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from billing.services import get_wallet
from llm import LLMError

from .forms import MessageForm, NewChatForm, RenameForm
from .models import Conversation
from .services import send_message

TEMPLATE = "chat/layout.html"


def has_credit(user):
    return get_wallet(user).balance_micros > 0


def sidebar_conversations(user):
    # Explicit order_by: keep the sidebar newest-first even if this query is ever annotated.
    return Conversation.objects.filter(owner=user).order_by("-updated_at", "-id")


def chat_context(request, conversation=None, **extra):
    context = {
        "conversation": conversation,
        "messages_list": conversation.messages.all() if conversation else [],
        "sidebar_conversations": sidebar_conversations(request.user),
        "out_of_credit": not has_credit(request.user),
        "max_chars": settings.CHAT_MESSAGE_MAX_CHARS,
        "model_available": model_available(conversation.llm_model) if conversation else True,
    }
    context.update(extra)
    return context


def model_available(model):
    return model.is_active and model.provider in settings.CHAT_PROVIDERS


@login_required
def chat_list(request):
    """The sidebar replaces the list page: open the most recent chat."""
    latest = sidebar_conversations(request.user).first()
    if latest is None:
        return redirect("chat_new")
    return redirect("chat_detail", pk=latest.pk)


@login_required
def chat_new(request):
    if request.method != "POST":
        return render(request, TEMPLATE, chat_context(request, form=NewChatForm()))

    form = NewChatForm(request.POST)
    context = chat_context(request, form=form)
    if not form.is_valid():
        return render(request, TEMPLATE, context, status=400)
    if context["out_of_credit"]:
        return render(request, TEMPLATE, context, status=402)
    try:
        conversation = send_message(
            request.user, form.cleaned_data["llm_model"], form.cleaned_data["content"]
        )
    except LLMError as error:
        context["error"] = error.message
        return render(request, TEMPLATE, context, status=error.status)
    return redirect(reverse("chat_detail", args=[conversation.pk]) + "#latest")


@login_required
def chat_detail(request, pk):
    conversation = get_object_or_404(
        Conversation.objects.select_related("llm_model"), pk=pk, owner=request.user
    )
    if request.method != "POST":
        return render(request, TEMPLATE, chat_context(request, conversation, form=MessageForm()))

    form = MessageForm(request.POST)
    context = chat_context(request, conversation, form=form)
    if not form.is_valid():
        return render(request, TEMPLATE, context, status=400)
    if not context["model_available"]:
        context["error"] = "This model is no longer available. Start a new chat."
        return render(request, TEMPLATE, context, status=400)
    if context["out_of_credit"]:
        return render(request, TEMPLATE, context, status=402)
    try:
        send_message(request.user, conversation.llm_model, form.cleaned_data["content"], conversation)
    except LLMError as error:
        context["error"] = error.message
        return render(request, TEMPLATE, context, status=error.status)
    return redirect(reverse("chat_detail", args=[conversation.pk]) + "#latest")


@login_required
@require_POST
def chat_rename(request, pk):
    conversation = get_object_or_404(
        Conversation.objects.select_related("llm_model"), pk=pk, owner=request.user
    )
    form = RenameForm(request.POST)
    if not form.is_valid():
        context = chat_context(
            request, conversation, form=MessageForm(), rename_form=form, rename_open=True
        )
        return render(request, TEMPLATE, context, status=400)
    # update() leaves updated_at alone, so renaming doesn't reorder the sidebar.
    Conversation.objects.filter(pk=conversation.pk).update(title=form.cleaned_data["title"])
    return redirect("chat_detail", pk=conversation.pk)
