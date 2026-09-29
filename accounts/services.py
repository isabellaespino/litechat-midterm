import math

from .models import UserSettings

MEMORIES_HEADER = "About the user (notes they asked you to remember):"


def get_settings(user):
    settings_row, _ = UserSettings.objects.get_or_create(user=user)
    return settings_row


def system_prompt_for(user):
    """The user's Global System Prompt, or None when they haven't set one."""
    return get_settings(user).system_prompt.strip() or None


def system_text_for(user):
    """The system text sent with every message: the Global System Prompt, then the
    user's memories as a list. None when neither is set (no system field at all)."""
    parts = []
    prompt = system_prompt_for(user)
    if prompt:
        parts.append(prompt)
    memories = [m.text for m in user.memories.all()]
    if memories:
        parts.append(MEMORIES_HEADER + "\n" + "\n".join(f"- {text}" for text in memories))
    return "\n\n".join(parts) or None


def estimated_system_tokens(user):
    """Rough tokens the system text adds to every message (about 4 characters per token)."""
    text = system_text_for(user)
    return math.ceil(len(text) / 4) if text else 0
