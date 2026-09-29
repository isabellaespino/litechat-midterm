from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from billing.services import get_wallet
from config.money import format_dollars
from llm import LLMError

from .forms import MessageForm, NewChatForm, RenameForm
from .models import Conversation
from . import titles
from .services import ConversationDeleted, send_message

TEMPLATE = "chat/layout.html"
OUT_OF_CREDIT = "You're out of credit. Contact an administrator to top up."


def wants_json(request):
    """True only for the chat script's fetch requests.

    Don't use request.accepts("application/json"): a normal browser form post sends
    "Accept: ..., */*", which accepts() would treat as JSON too.
    """
    return request.headers.get("Accept", "").startswith("application/json")


def chat_login_required(view):
    """login_required, except fetch requests get a 401 instead of a redirect.

    fetch() silently follows redirects, so a redirect to the log-in page would reach
    the script as a 200 HTML page.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            if wants_json(request):
                return JsonResponse(
                    {"error": "Please log in again.", "login_url": reverse("login")},
                    status=401,
                )
            return redirect_to_login(request.get_full_path())
        return view(request, *args, **kwargs)

    return wrapper


def has_credit(user):
    return get_wallet(user).balance_micros > 0


def balance_display(user):
    """The balance exactly as the nav shows it ("My Profile · $1.99")."""
    return format_dollars(get_wallet(user).balance_micros)


def sidebar_conversations(user):
    # Explicit order_by: keep the sidebar newest-first even if this query is ever annotated.
    return Conversation.objects.filter(owner=user).order_by("-updated_at", "-id")


def model_available(model):
    return model.is_active and model.provider in settings.CHAT_PROVIDERS


def switch_checked(form, conversation):
    """What the "Include memories" switch shows: the posted value after a failed send,
    otherwise the chat's saved value (on for a new chat)."""
    if form is not None and form.is_bound and form.data.get("memories_switch"):
        return bool(form.data.get("include_memories"))
    return conversation.include_memories if conversation is not None else True


def chat_context(request, conversation=None, **extra):
    context = {
        "user_memory_count": request.user.memories.count(),
        "memories_switch_checked": switch_checked(extra.get("form"), conversation),
        "conversation": conversation,
        "messages_list": conversation.messages.all() if conversation else [],
        "sidebar_conversations": sidebar_conversations(request.user),
        "out_of_credit": not has_credit(request.user),
        "max_chars": settings.CHAT_MESSAGE_MAX_CHARS,
        "model_available": model_available(conversation.llm_model) if conversation else True,
    }
    context.update(extra)
    return context


def respond_error(request, context, status, error=None, **json_extra):
    """The same failure as a full page (form post) or as JSON (fetch), same status."""
    if wants_json(request):
        return JsonResponse({"error": error, **json_extra}, status=status)
    if error:
        context["error"] = error
    return render(request, TEMPLATE, context, status=status)


def invalid_form(request, context, form):
    if not wants_json(request):
        return respond_error(request, context, 400)  # the page shows field errors itself
    errors = form.errors.get_json_data()
    message = " ".join(e["message"] for field in errors.values() for e in field)
    return respond_error(request, context, 400, message, field_errors=errors)


def out_of_credit(request, context):
    if not wants_json(request):
        return respond_error(request, context, 402)
    return respond_error(
        request, context, 402, OUT_OF_CREDIT,
        out_of_credit=True, balance=balance_display(request.user),
    )


def sidebar_html(request, conversation):
    return render_to_string(
        "chat/_sidebar.html",
        {"sidebar_conversations": sidebar_conversations(request.user), "conversation": conversation},
        request=request,
    )


@chat_login_required
def chat_list(request):
    """The sidebar replaces the list page: open the most recent chat."""
    latest = sidebar_conversations(request.user).first()
    if latest is None:
        return redirect("chat_new")
    return redirect("chat_detail", pk=latest.pk)


@chat_login_required
def chat_new(request):
    if request.method != "POST":
        return render(request, TEMPLATE, chat_context(request, form=NewChatForm()))

    form = NewChatForm(request.POST)
    context = chat_context(request, form=form)
    if not form.is_valid():
        return invalid_form(request, context, form)
    if context["out_of_credit"]:
        return out_of_credit(request, context)
    try:
        conversation = send_message(
            request.user,
            form.cleaned_data["llm_model"],
            form.cleaned_data["content"],
            include_memories=form.include_memories_for(None),
        )
    except LLMError as error:
        return respond_error(request, context, error.status, error.message)

    chat_url = reverse("chat_detail", args=[conversation.pk])
    if not wants_json(request):
        return redirect(chat_url + "#latest")
    main_html = render_to_string(
        "chat/_main.html", chat_context(request, conversation, form=MessageForm()), request=request
    )
    return JsonResponse(
        {
            "chat_url": chat_url,
            "main_html": main_html,
            "sidebar_html": sidebar_html(request, conversation),
            "balance": balance_display(request.user),
        }
    )


@chat_login_required
def chat_detail(request, pk):
    conversation = (
        Conversation.objects.select_related("llm_model").filter(pk=pk, owner=request.user).first()
    )
    if conversation is None:
        if wants_json(request):
            return JsonResponse({"error": "Chat not found."}, status=404)
        raise Http404("No such chat.")
    if request.method != "POST":
        return render(request, TEMPLATE, chat_context(request, conversation, form=MessageForm()))

    form = MessageForm(request.POST)
    context = chat_context(request, conversation, form=form)
    if not form.is_valid():
        return invalid_form(request, context, form)
    if not context["model_available"]:
        return respond_error(
            request, context, 400, "This model is no longer available. Start a new chat."
        )
    if context["out_of_credit"]:
        return out_of_credit(request, context)
    try:
        conversation = send_message(
            request.user,
            conversation.llm_model,
            form.cleaned_data["content"],
            conversation,
            include_memories=form.include_memories_for(conversation),
        )
    except LLMError as error:
        return respond_error(request, context, error.status, error.message)
    except ConversationDeleted:
        # Deleted (e.g. from another tab) while the reply was in flight. The reply was
        # still charged; nothing else was saved.
        if wants_json(request):
            return JsonResponse({"error": "This chat was deleted."}, status=404)
        raise Http404("This chat was deleted.")

    if not wants_json(request):
        return redirect(reverse("chat_detail", args=[conversation.pk]) + "#latest")
    messages_html = "".join(
        render_to_string(
            "chat/_message.html", {"message": m, "conversation": conversation}, request=request
        )
        for m in conversation.new_messages
    )
    return JsonResponse(
        {
            "messages_html": messages_html,
            "sidebar_html": sidebar_html(request, conversation),
            "balance": balance_display(request.user),
        }
    )


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
    Conversation.objects.filter(pk=conversation.pk).update(
        title=form.cleaned_data["title"], title_source=Conversation.TitleSource.USER
    )
    return redirect("chat_detail", pk=conversation.pk)


@chat_login_required
@require_http_methods(["GET", "POST"])
def chat_delete(request, pk):
    """GET: confirmation page. POST: delete the chat and its messages.

    Charges for its replies stay in the ledger unchanged (their message link becomes
    NULL): no refund, and the balance doesn't move.
    """
    conversation = get_object_or_404(Conversation, pk=pk, owner=request.user)
    if request.method == "POST":
        conversation.delete()
        messages.success(request, "Chat deleted.")
        return redirect("chat_list")
    return render(request, "chat/confirm_delete.html", {"conversation": conversation})


@chat_login_required
@require_POST
def chat_title(request, pk):
    """Ask the chat's own model for an automatic title (called by the script).

    JSON only. Free to the user: nothing is charged and the response has no balance.
    Not gated on credit: every new chat gets an attempt (loop 7, decision #1).
    """
    conversation = (
        Conversation.objects.select_related("llm_model", "owner")
        .filter(pk=pk, owner=request.user)
        .first()
    )
    if conversation is None:
        return JsonResponse({"error": "Chat not found."}, status=404)
    result, detail = titles.generate_title(conversation)
    if result == titles.OK:
        return JsonResponse(
            {"changed": True, "title": detail, "sidebar_html": sidebar_html(request, conversation)}
        )
    if result == titles.UNUSABLE:
        return JsonResponse({"changed": False, "title": conversation.title})
    if result == titles.FAILED:
        return JsonResponse({"error": detail.message}, status=detail.status)
    if result == titles.DELETED:
        return JsonResponse({"error": "This chat was deleted."}, status=404)
    return JsonResponse({"error": "This chat's title isn't waiting for an automatic title."}, status=409)
