from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import SYSTEM_PROMPT_MAX_CHARS


class SignUpForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        fields = ("username",)


class SystemPromptForm(forms.Form):
    system_prompt = forms.CharField(
        label="Global System Prompt",
        required=False,
        max_length=SYSTEM_PROMPT_MAX_CHARS,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "e.g. Answer concisely, in British English."}),
    )
