from django import forms
from django.conf import settings

from catalog.models import LLMModel


def chat_models():
    """Active models whose provider can be used in chat."""
    return LLMModel.objects.filter(is_active=True, provider__in=settings.CHAT_PROVIDERS)


def model_label(model):
    # No prices here: costs live on My Profile and /models/, not in the chat pages.
    return f"{model.display_name} · {model.get_tier_display()}"


class MessageForm(forms.Form):
    content = forms.CharField(
        label="Message",
        max_length=settings.CHAT_MESSAGE_MAX_CHARS,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Type your message…"}),
    )


class NewChatForm(MessageForm):
    llm_model = forms.ChoiceField(label="Model", widget=forms.Select(attrs={"aria-label": "Model"}))
    field_order = ["llm_model", "content"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        groups = {}
        for model in chat_models():
            groups.setdefault(model.get_provider_display(), []).append(
                (str(model.pk), model_label(model))
            )
        self.fields["llm_model"].choices = list(groups.items())

    def clean_llm_model(self):
        return chat_models().get(pk=self.cleaned_data["llm_model"])
