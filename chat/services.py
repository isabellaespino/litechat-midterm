import re

from django.db import DatabaseError, transaction

import llm
from accounts.services import system_prompt_for
from billing.models import CreditTransaction
from billing.services import post_transaction, reply_cost_micros

from .models import Conversation, Message

TITLE_MAX_CHARS = 50


class ConversationDeleted(Exception):
    """The chat was deleted while its reply was in flight.

    The reply's tokens were used and paid for, so its charge was still recorded
    (with no message); nothing else was saved. Views turn this into a 404.
    """


def _conversation_exists(pk):
    return Conversation.objects.filter(pk=pk).exists()


def _charge_reply_in_deleted_chat(user, cost, conversation):
    post_transaction(
        user,
        -cost,
        CreditTransaction.Kind.CHARGE,
        note=f"Reply in deleted chat “{conversation.title}”",
        message=None,
    )


def title_from(text):
    """A chat title from the first line of the first message."""
    lines = text.strip().splitlines()
    first_line = re.sub(r"\s+", " ", lines[0]).strip() if lines else ""
    if not first_line:
        return "New chat"
    if len(first_line) > TITLE_MAX_CHARS:
        return first_line[: TITLE_MAX_CHARS - 1].rstrip() + "…"
    return first_line


def history_for(conversation):
    if conversation is None:
        return []
    return [
        {"role": m.role, "content": m.content} for m in conversation.messages.all()
    ]


def send_message(user, llm_model, text, conversation=None):
    """Send `text` (plus the stored history) to the model and charge the reply.

    The proxy is called outside any transaction. If it fails, LLMError propagates
    and nothing is saved or charged. The caller is responsible for blocking users
    whose balance is $0 or less; the actual cost is charged even if the balance
    goes negative.

    If `conversation` is deleted while the proxy call is in flight, the reply is
    still charged and ConversationDeleted is raised.
    """
    messages = history_for(conversation) + [{"role": "user", "content": text}]
    # The user's Global System Prompt, read at send time (None when not set).
    reply = llm.complete(llm_model, messages, system=system_prompt_for(user))

    cost = reply_cost_micros(
        reply.input_tokens,
        reply.output_tokens,
        llm_model.input_price_micros_per_mtok,
        llm_model.output_price_micros_per_mtok,
    )
    existing = conversation is not None
    deleted = False
    try:
        with transaction.atomic():
            if existing and not _conversation_exists(conversation.pk):
                # Deleted during the proxy call: charge the reply, save nothing else.
                _charge_reply_in_deleted_chat(user, cost, conversation)
                deleted = True
            else:
                conversation, user_message, assistant = _save_exchange(
                    user, llm_model, text, conversation, reply, cost
                )
    except DatabaseError:
        # Backstop: the chat vanished between the check and the writes (the failed
        # writes were rolled back). Record the charge on its own.
        if not existing or _conversation_exists(conversation.pk):
            raise
        with transaction.atomic():
            _charge_reply_in_deleted_chat(user, cost, conversation)
        deleted = True
    if deleted:
        # Raised after the transaction committed, so the charge is kept.
        raise ConversationDeleted()

    # The exchange this call created, for callers that render just the new messages.
    conversation.new_messages = [user_message, assistant]
    return conversation


def _save_exchange(user, llm_model, text, conversation, reply, cost):
    """Save both messages, charge the reply and bump the chat (inside the caller's
    transaction). Returns (conversation, user_message, assistant)."""
    if conversation is None:
        conversation = Conversation.objects.create(
            owner=user, llm_model=llm_model, title=title_from(text)
        )
    user_message = Message.objects.create(
        conversation=conversation, role=Message.Role.USER, content=text
    )
    assistant = Message.objects.create(
        conversation=conversation,
        role=Message.Role.ASSISTANT,
        content=reply.text,
        input_tokens=reply.input_tokens,
        output_tokens=reply.output_tokens,
        cost_micros=cost,
        stop_reason=reply.stop_reason,
        usage_estimated=reply.usage_estimated,
        input_price_micros_per_mtok=llm_model.input_price_micros_per_mtok,
        output_price_micros_per_mtok=llm_model.output_price_micros_per_mtok,
    )
    post_transaction(
        user,
        -cost,
        CreditTransaction.Kind.CHARGE,
        note=f"Reply in “{conversation.title}”",
        message=assistant,
    )
    conversation.save(update_fields=["updated_at"])
    return conversation, user_message, assistant
