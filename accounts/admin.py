from django.contrib import admin

from .models import Memory, UserSettings


class UserSettingsInline(admin.StackedInline):
    """Read-only view of a user's Global System Prompt, for support."""

    model = UserSettings
    fields = ["system_prompt", "updated_at"]
    readonly_fields = fields
    can_delete = False
    verbose_name = verbose_name_plural = "Global System Prompt"

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class MemoryInline(admin.TabularInline):
    """Read-only view of a user's memories, for support."""

    model = Memory
    fields = ["text", "created_at"]
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
