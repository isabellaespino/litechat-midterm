from django.contrib import admin
from django.db.models import Count, Sum
from django.urls import reverse
from django.utils.html import format_html

from config.money import format_dollars_precise

from .models import Conversation, Message, TitleGeneration


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


@admin.register(TitleGeneration)
class TitleGenerationAdmin(admin.ModelAdmin):
    """What automatic titles cost the app. Admin-only; never shown to users."""

    list_display = ["created_at", "user", "chat", "llm_model", "status", "input_tokens", "output_tokens", "cost"]
    list_filter = ["status", "llm_model"]
    search_fields = ["user__username", "title"]
    readonly_fields = [
        "created_at", "user", "chat", "llm_model", "status", "title", "input_tokens", "output_tokens",
        "usage_estimated", "input_price_micros_per_mtok", "output_price_micros_per_mtok", "cost", "error_status",
    ]
    fields = readonly_fields

    @admin.display(description="Chat")
    def chat(self, obj):
        if obj.conversation_id is None:
            return "(deleted)"
        url = reverse("admin:chat_conversation_change", args=[obj.conversation_id])
        return format_html('<a href="{}">{}</a>', url, obj.conversation.title)

    @admin.display(description="Cost (app)", ordering="cost_micros")
    def cost(self, obj):
        return format_dollars_precise(obj.cost_micros)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "conversation", "llm_model")

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context)
        try:
            shown = response.context_data["cl"].queryset
        except (AttributeError, KeyError):
            return response  # e.g. a redirect
        total = shown.aggregate(t=Sum("cost_micros"))["t"] or 0
        response.context_data["title"] = (
            f"Title generations (app cost) · total for the rows shown: {format_dollars_precise(total)}"
        )
        return response

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
