from django.conf import settings
from django.db import models


class Conversation(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations"
    )
    title = models.CharField(max_length=100, default="New chat")
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
    def was_cut_off(self):
        return self.stop_reason == "length"
