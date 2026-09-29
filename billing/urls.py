from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path("profile/", views.profile, name="profile"),
    # The old credit page moved to My Profile.
    path("credit/", RedirectView.as_view(pattern_name="profile", permanent=True)),
]
