from django import forms
from django.contrib import admin

from config.money import dollars_to_micros, format_dollars_precise, micros_to_dollars

from .models import LLMModel

PRICE_FIELD = dict(max_digits=12, decimal_places=6, min_value=0)


class LLMModelForm(forms.ModelForm):
    """Admins enter prices in dollars per 1M tokens; they are stored as micro-dollars."""

    input_price = forms.DecimalField(label="Input price ($ per 1M tokens)", **PRICE_FIELD)
    output_price = forms.DecimalField(label="Output price ($ per 1M tokens)", **PRICE_FIELD)

    class Meta:
        model = LLMModel
        exclude = ["input_price_micros_per_mtok", "output_price_micros_per_mtok"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["input_price"].initial = micros_to_dollars(
                self.instance.input_price_micros_per_mtok
            )
            self.fields["output_price"].initial = micros_to_dollars(
                self.instance.output_price_micros_per_mtok
            )

    def save(self, commit=True):
        self.instance.input_price_micros_per_mtok = dollars_to_micros(
            self.cleaned_data["input_price"]
        )
        self.instance.output_price_micros_per_mtok = dollars_to_micros(
            self.cleaned_data["output_price"]
        )
        return super().save(commit)


@admin.register(LLMModel)
class LLMModelAdmin(admin.ModelAdmin):
    form = LLMModelForm
    list_display = [
        "display_name",
        "provider",
        "api_model_id",
        "tier",
        "input_price",
        "output_price",
        "is_active",
    ]
    list_filter = ["provider", "tier", "is_active"]
    search_fields = ["display_name", "api_model_id"]
    fields = [
        "provider",
        "api_model_id",
        "display_name",
        "description",
        "tier",
        "input_price",
        "output_price",
        "is_active",
        "sort_order",
    ]

    @admin.display(description="Input $/1M", ordering="input_price_micros_per_mtok")
    def input_price(self, obj):
        return format_dollars_precise(obj.input_price_micros_per_mtok)

    @admin.display(description="Output $/1M", ordering="output_price_micros_per_mtok")
    def output_price(self, obj):
        return format_dollars_precise(obj.output_price_micros_per_mtok)
