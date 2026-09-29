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
    # Loop 8: the "Include memories" switch. An unchecked checkbox isn't submitted, so
    # the hidden `memories_switch` marker (rendered only when the switch is shown)
    # tells "switched off" apart from "no switch on the page".
    include_memories = forms.BooleanField(required=False)
    memories_switch = forms.BooleanField(required=False, widget=forms.HiddenInput)

    def include_memories_for(self, conversation):
        """The switch value for this send, or the chat's saved value (on for a new
        chat) when the switch wasn't on the page."""
        if self.cleaned_data.get("memories_switch"):
            return bool(self.cleaned_data.get("include_memories"))
        return conversation.include_memories if conversation is not None else True


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


class RenameForm(forms.Form):
    title = forms.CharField(label="Chat title", max_length=100)
