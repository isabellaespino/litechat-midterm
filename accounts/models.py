from django.conf import settings
from django.db import models

SYSTEM_PROMPT_MAX_CHARS = 4000


class UserSettings(models.Model):
    """Per-user preferences. Created on first use (see accounts.services.get_settings)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="chat_settings",
    )
    # The Global System Prompt: sent as the system prompt in every chat, for every
    # provider. Empty means no system prompt at all.
    system_prompt = models.TextField(blank=True, max_length=SYSTEM_PROMPT_MAX_CHARS)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "user settings"
        verbose_name_plural = "user settings"

    def __str__(self):
        return f"Settings for {self.user}"

MEMORY_MAX_COUNT = 10
MEMORY_MAX_CHARS = 200


class Memory(models.Model):
    """A short note the user asked every model to remember (loop 7).

    Sent with the Global System Prompt in every chat, so the count and length are
    capped: they're billed as input tokens on every message. Only the user adds them.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memories")
    text = models.CharField(max_length=MEMORY_MAX_CHARS)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name_plural = "memories"

    def __str__(self):
        return self.text
