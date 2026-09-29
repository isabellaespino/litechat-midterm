from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import CreateView

from billing.views import render_profile

from .forms import SignUpForm, SystemPromptForm
from .services import get_settings


class SignUpView(CreateView):
    form_class = SignUpForm
    template_name = "registration/signup.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("home")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        kwargs.setdefault("signup_credit_micros", settings.SIGNUP_CREDIT_MICROS)
        return super().get_context_data(**kwargs)

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        return redirect("home")

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form), status=400)


class LoginView(auth_views.LoginView):
    redirect_authenticated_user = True

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form), status=400)


@login_required
@require_POST
def system_prompt(request):
    """Save (or clear) the Global System Prompt shown on My Profile."""
    form = SystemPromptForm(request.POST)
    if not form.is_valid():
        return render_profile(request, status=400, system_prompt_form=form)
    user_settings = get_settings(request.user)
    user_settings.system_prompt = form.cleaned_data["system_prompt"]
    user_settings.save()
    messages.success(
        request,
        "System prompt saved." if user_settings.system_prompt else "System prompt cleared.",
    )
    return redirect(reverse("profile") + "#system-prompt")
