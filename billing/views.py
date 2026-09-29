from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import render

from chat.models import Conversation, Message

from .models import CreditTransaction
from .services import get_wallet

CHATS_PER_PAGE = 20


@login_required
def profile(request):
    return render_profile(request)


def render_profile(request, status=200, **extra):
    """My Profile. Also used to re-show the page with a 400 from the system prompt form."""
    from accounts.forms import SystemPromptForm
    from accounts.services import get_settings

    user = request.user
    ledger = user.credit_transactions.all()
    charge = CreditTransaction.Kind.CHARGE
    total_added = ledger.exclude(kind=charge).aggregate(t=Sum("amount_micros"))["t"] or 0
    total_spent = -(ledger.filter(kind=charge).aggregate(t=Sum("amount_micros"))["t"] or 0)
    # Charges whose chat was deleted: the ledger keeps them (no refund), so show them
    # as one line to keep per-chat usage reconciled with total spend.
    deleted = ledger.filter(kind=charge, message__isnull=True).aggregate(
        total=Sum("amount_micros"), count=Count("id")
    )

    conversations = (
        Conversation.objects.filter(owner=user)
        .select_related("llm_model")
        .annotate(
            reply_count=Count("messages", filter=Q(messages__role=Message.Role.ASSISTANT)),
            input_tokens_total=Sum("messages__input_tokens"),
            output_tokens_total=Sum("messages__output_tokens"),
            total_cost=Sum("messages__cost_micros"),
        )
        # Meta.ordering is ignored on aggregated querysets, so order explicitly.
        .order_by("-updated_at", "-id")
    )
    page = Paginator(conversations, CHATS_PER_PAGE).get_page(request.GET.get("page"))

    # One query for the replies of every chat on this page (no N+1).
    replies = {}
    for message in Message.objects.filter(
        conversation__in=[c.pk for c in page], role=Message.Role.ASSISTANT
    ):
        replies.setdefault(message.conversation_id, []).append(message)
    for conversation in page:
        conversation.replies = replies.get(conversation.pk, [])

    return render(
        request,
        "billing/profile.html",
        {
            "wallet": get_wallet(user),
            "total_added": total_added,
            "total_spent": total_spent,
            "page": page,
            "credit_added": ledger.exclude(kind=charge),
            "deleted_replies": deleted["count"],
            "deleted_spent": -(deleted["total"] or 0),
            "system_prompt_form": extra.pop(
                "system_prompt_form",
                SystemPromptForm(initial={"system_prompt": get_settings(user).system_prompt}),
            ),
            **extra,
        },
        status=status,
    )
