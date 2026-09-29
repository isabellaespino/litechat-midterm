from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.urls import reverse
from django.utils.html import format_html

from accounts.admin import UserSettingsInline
from config.money import dollars_to_micros, format_dollars, format_dollars_precise

from .models import CreditTransaction, Wallet
from .services import record_transaction

User = get_user_model()


class CreditTransactionForm(forms.ModelForm):
    """Admins enter amounts in dollars; they are stored as micro-dollars."""

    amount = forms.DecimalField(
        label="Amount ($)",
        max_digits=12,
        decimal_places=6,
        help_text="Positive adds credit. Adjustments may be negative.",
    )
    kind = forms.ChoiceField(
        choices=[
            (CreditTransaction.Kind.TOPUP, CreditTransaction.Kind.TOPUP.label),
            (CreditTransaction.Kind.ADJUSTMENT, CreditTransaction.Kind.ADJUSTMENT.label),
        ]
    )

    class Meta:
        model = CreditTransaction
        fields = ["user", "kind", "note"]

    def clean(self):
        cleaned = super().clean()
        amount = cleaned.get("amount")
        if amount is not None:
            if amount == 0:
                self.add_error("amount", "Amount can't be zero.")
            elif cleaned.get("kind") == CreditTransaction.Kind.TOPUP and amount < 0:
                self.add_error("amount", "A top-up must be positive. Use an adjustment to remove credit.")
        return cleaned


@admin.register(CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
    """Append-only: admins can add top-ups and adjustments but never edit or delete."""

    form = CreditTransactionForm
    list_display = ["created_at", "user", "kind", "amount", "note", "created_by", "conversation"]
    list_filter = ["kind", "created_at"]
    search_fields = ["user__username", "note"]
    autocomplete_fields = ["user"]
    readonly_fields = ["user", "kind", "amount", "note", "conversation", "created_by", "created_at"]

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields if obj else []

    def get_form(self, request, obj=None, **kwargs):
        if obj is not None:
            # Existing entries are shown read-only, so the dollar-entry form isn't needed.
            kwargs["form"] = forms.ModelForm
        return super().get_form(request, obj, **kwargs)

    def get_fields(self, request, obj=None):
        return self.readonly_fields if obj else ["user", "amount", "kind", "note"]

    @admin.display(description="Amount", ordering="amount_micros")
    def amount(self, obj):
        return format_dollars_precise(obj.amount_micros)

    @admin.display(description="Chat")
    def conversation(self, obj):
        if obj.message_id is None:
            return ""
        conversation = obj.message.conversation
        url = reverse("admin:chat_conversation_change", args=[conversation.pk])
        return format_html('<a href="{}">{}</a>', url, conversation.title)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "created_by", "message__conversation")

    def save_model(self, request, obj, form, change):
        obj.amount_micros = dollars_to_micros(form.cleaned_data["amount"])
        obj.created_by = request.user
        record_transaction(obj)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    """Read-only. Balances change only through ledger entries."""

    list_display = ["user", "available_credit", "transactions", "updated_at"]
    search_fields = ["user__username"]
    fields = ["user", "available_credit", "transactions", "updated_at"]
    readonly_fields = fields

    @admin.display(description="Available credit", ordering="balance_micros")
    def available_credit(self, obj):
        return format_dollars(obj.balance_micros)

    @admin.display(description="Ledger")
    def transactions(self, obj):
        url = reverse("admin:billing_credittransaction_changelist")
        return format_html('<a href="{}?user__id__exact={}">View transactions</a>', url, obj.user_id)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class WalletInline(admin.StackedInline):
    model = Wallet
    fields = ["available_credit"]
    readonly_fields = ["available_credit"]
    can_delete = False

    @admin.display(description="Available credit")
    def available_credit(self, obj):
        return format_dollars(obj.balance_micros)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


admin.site.unregister(User)


@admin.register(User)
class UserWithWalletAdmin(UserAdmin):
    inlines = [*UserAdmin.inlines, WalletInline, UserSettingsInline]
