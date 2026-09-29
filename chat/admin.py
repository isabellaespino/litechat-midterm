from django.contrib import admin
from django.db.models import Count, Sum

from config.money import format_dollars_precise

from .models import Conversation, Message


class MessageInline(admin.TabularInline):
    model = Message
    fields = ["created_at", "role", "content", "input_tokens", "output_tokens", "cost", "stop_reason"]
    readonly_fields = fields
    extra = 0
    can_delete = False

    @admin.display(description="Cost")
    def cost(self, obj):
        return format_dollars_precise(obj.cost_micros) if obj.role == Message.Role.ASSISTANT else ""

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    """Read-only, for support."""

    list_display = ["title", "owner", "llm_model", "message_count", "total_cost", "updated_at"]
    list_filter = ["llm_model"]
    search_fields = ["title", "owner__username"]
    fields = ["title", "owner", "llm_model", "total_cost", "created_at", "updated_at"]
    readonly_fields = fields
    inlines = [MessageInline]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(_message_count=Count("messages"), _total_cost=Sum("messages__cost_micros"))
        )

    @admin.display(description="Messages", ordering="_message_count")
    def message_count(self, obj):
        return obj._message_count

    @admin.display(description="Total cost", ordering="_total_cost")
    def total_cost(self, obj):
        return format_dollars_precise(obj._total_cost or 0)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
