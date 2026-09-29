from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import MEMORY_MAX_CHARS, MEMORY_MAX_COUNT, SYSTEM_PROMPT_MAX_CHARS, Memory


class SignUpForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        fields = ("username",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password2"].label = "Confirm password"


class SystemPromptForm(forms.Form):
    system_prompt = forms.CharField(
        label="Global System Prompt",
        required=False,
        max_length=SYSTEM_PROMPT_MAX_CHARS,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "e.g. Answer concisely, in British English."}),
    )


class MemoryForm(forms.Form):
    text = forms.CharField(
        label="Add a memory",
        max_length=MEMORY_MAX_CHARS,
        widget=forms.TextInput(attrs={"placeholder": "e.g. I'm a student", "maxlength": MEMORY_MAX_CHARS}),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_text(self):
        text = self.cleaned_data["text"]
        existing = Memory.objects.filter(user=self.user)
        if existing.count() >= MEMORY_MAX_COUNT:
            raise forms.ValidationError(
                f"You can keep up to {MEMORY_MAX_COUNT} memories. Delete one to add another."
            )
        if existing.filter(text__iexact=text).exists():
            raise forms.ValidationError("You already have that memory.")
        return text
