"""Automatic chat titles (loop 7).

After a new chat's first reply, the script asks for a short title from the chat's own
model. The app pays for these calls: nothing touches the user's wallet or ledger, and
each attempt is logged in TitleGeneration for admins only.
"""

import re

from django.conf import settings
from django.db import transaction

import llm
from billing.services import reply_cost_micros

from .models import Conversation, TitleGeneration

TITLE_EXCERPT_CHARS = 1000
AUTO_TITLE_MAX_CHARS = 60
INSTRUCTION = (
    "Write a short title (3 to 6 words) for this conversation. Reply with the title only: "
    "no quotes, no Markdown, no ending punctuation. Use the conversation's language."
)
_UNUSABLE = {"title", "untitled", "new chat", "chat"}

Source = Conversation.TitleSource
Status = TitleGeneration.Status

# Results of generate_title()
OK, UNUSABLE, CONFLICT, FAILED, DELETED = "ok", "unusable", "conflict", "failed", "deleted"


def build_title_prompt(conversation):
    """The fixed instruction plus the (truncated) first message and first reply."""
    first_user = first_reply = ""
    for message in conversation.messages.all()[:2]:
        if message.role == "user" and not first_user:
            first_user = message.content
        elif message.role == "assistant" and not first_reply:
            first_reply = message.content
    return (
        f"{INSTRUCTION}\n\n"
        f"User: {first_user[:TITLE_EXCERPT_CHARS]}\n"
        f"Assistant: {first_reply[:TITLE_EXCERPT_CHARS]}"
    )


def clean_title(text):
    """Model output -> a tidy title, or "" when nothing usable is left."""
    line = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
    line = re.sub(r"[*_`#]", "", line)  # Markdown emphasis, code and heading marks
    line = line.strip().strip("\"'“”‘’«» ").strip()
    line = re.sub(r"^title\s*:\s*", "", line, flags=re.IGNORECASE)
    line = line.strip("\"'“”‘’«» ")
    line = re.sub(r"\s+", " ", line).rstrip(".:;").strip()
    if not re.search(r"\w", line) or line.lower() in _UNUSABLE:
        return ""
    if len(line) > AUTO_TITLE_MAX_CHARS:
        line = line[: AUTO_TITLE_MAX_CHARS - 1].rstrip() + "…"
    return line


def _log(conversation, exists, status, **fields):
    model = conversation.llm_model
    TitleGeneration.objects.create(
        conversation=conversation if exists else None,
        user=conversation.owner,
        llm_model=model,
        status=status,
        input_price_micros_per_mtok=model.input_price_micros_per_mtok,
        output_price_micros_per_mtok=model.output_price_micros_per_mtok,
        **fields,
    )


def generate_title(conversation):
    """Try to give a provisional chat an automatic title.

    Returns (result, detail): (OK, title), (UNUSABLE, None), (CONFLICT, None),
    (FAILED, LLMError) or (DELETED, None). Never charges the user.
    """
    # Claim the chat, so only one request ever calls the model for it.
    claimed = Conversation.objects.filter(
        pk=conversation.pk, title_source=Source.PROVISIONAL
    ).update(title_source=Source.GENERATING)
    if not claimed:
        return CONFLICT, None

    model = conversation.llm_model
    prompt = build_title_prompt(conversation)
    try:
        # Outside any transaction: this is a network call. No system prompt or memories.
        reply = llm.complete(
            model,
            [{"role": "user", "content": prompt}],
            system=None,
            max_output_tokens=settings.TITLE_MAX_OUTPUT_TOKENS,
            timeout=settings.TITLE_TIMEOUT_SECONDS,
        )
    except llm.LLMError as error:
        with transaction.atomic():
            chat = Conversation.objects.filter(pk=conversation.pk)
            exists = chat.exists()
            chat.filter(title_source=Source.GENERATING).update(title_source=Source.FAILED)
            _log(conversation, exists, Status.FAILED, error_status=error.status)
        return FAILED, error

    title = clean_title(reply.text)
    usage = dict(
        input_tokens=reply.input_tokens,
        output_tokens=reply.output_tokens,
        usage_estimated=reply.usage_estimated,
        cost_micros=reply_cost_micros(
            reply.input_tokens,
            reply.output_tokens,
            model.input_price_micros_per_mtok,
            model.output_price_micros_per_mtok,
        ),
    )
    with transaction.atomic():
        chat = Conversation.objects.filter(pk=conversation.pk)
        if not chat.exists():
            _log(conversation, False, Status.CHAT_DELETED, title=title, **usage)
            return DELETED, None
        generating = chat.filter(title_source=Source.GENERATING)
        if not title:
            if generating.update(title_source=Source.FAILED):
                _log(conversation, True, Status.UNUSABLE, **usage)
                return UNUSABLE, None
        # update(), so the title doesn't bump updated_at or reorder the sidebar.
        elif generating.update(title=title, title_source=Source.AUTO):
            _log(conversation, True, Status.OK, title=title, **usage)
            return OK, title
        # The user renamed the chat while the call was in flight: their title wins.
        _log(conversation, True, Status.SUPERSEDED, title=title, **usage)
        return CONFLICT, None
