from .models import UserSettings


def get_settings(user):
    settings_row, _ = UserSettings.objects.get_or_create(user=user)
    return settings_row


def system_prompt_for(user):
    """The user's Global System Prompt, or None when they haven't set one."""
    return get_settings(user).system_prompt.strip() or None
