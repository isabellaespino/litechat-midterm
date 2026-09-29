from django.conf import settings
from django.db import models


class Conversation(models.Model):
    class TitleSource(models.TextChoices):
        # A new chat starts "provisional" (the first line of its first message) and the
        # script then asks for an automatic title. "user" is a rename (or a chat that
        # predates automatic titles) and is never auto-titled.
        PROVISIONAL = "provisional", "Provisional (first line)"
        GENERATING = "generating", "Generating"
        AUTO = "auto", "Automatic"
        USER = "user", "Set by the user"
        FAILED = "failed", "Automatic title failed"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations"
    )
    title = models.CharField(max_length=100, default="New chat")
    title_source = models.CharField(max_length=20, choices=TitleSource.choices, default=TitleSource.USER)
    # Loop 8: whether this chat sends the user's memories (the Global System Prompt is
    # always sent). On for new chats; existing chats default to on, as in loop 7.
    include_memories = models.BooleanField(default=True)
    llm_model = models.ForeignKey(
        "catalog.LLMModel", on_delete=models.PROTECT, related_name="conversations"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]

    def __str__(self):
        return self.title


class Message(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    # Assistant replies only: usage and what it cost.
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cost_micros = models.BigIntegerField(default=0)
    stop_reason = models.CharField(max_length=40, blank=True)
    usage_estimated = models.BooleanField(default=False)
    # Prices applied to this reply, so later catalog edits don't rewrite history.
    input_price_micros_per_mtok = models.PositiveBigIntegerField(null=True, blank=True)
    output_price_micros_per_mtok = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.get_role_display()} message in “{self.conversation}”"

    @property
    def was_blocked(self):
        """The provider's safety filter declined to answer (Google "SAFETY")."""
        return self.stop_reason == "safety"

    @property
    def was_cut_off(self):
        return self.stop_reason == "length"


class TitleGeneration(models.Model):
    """Admin-only log of automatic title calls: what they cost the app.

    Titles are free to users (loop 7, decision #1), so this is deliberately NOT
    linked to the user's ledger or wallet and is never shown to users.
    """

    class Status(models.TextChoices):
        OK = "ok", "Title saved"
        UNUSABLE = "unusable", "Unusable answer"
        SUPERSEDED = "superseded", "Renamed during the call"
        CHAT_DELETED = "chat_deleted", "Chat deleted during the call"
        FAILED = "failed", "Proxy call failed"

    conversation = models.ForeignKey(
        Conversation, on_delete=models.SET_NULL, null=True, blank=True, related_name="title_generations"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    llm_model = models.ForeignKey("catalog.LLMModel", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=20, choices=Status.choices)
    title = models.CharField(max_length=100, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    usage_estimated = models.BooleanField(default=False)
    input_price_micros_per_mtok = models.PositiveBigIntegerField(default=0)
    output_price_micros_per_mtok = models.PositiveBigIntegerField(default=0)
    cost_micros = models.BigIntegerField(default=0)
    error_status = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "title generation (app cost)"
        verbose_name_plural = "title generations (app cost)"

    def __str__(self):
        return f"{self.get_status_display()} · {self.llm_model} · {self.cost_micros} µ$"
