from django.contrib import admin
from django.urls import include, path

from accounts import views as account_views

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("accounts/", include("accounts.urls")),
    path("models/", include("catalog.urls")),
    path("", include("billing.urls")),
    path("profile/system-prompt/", account_views.system_prompt, name="system_prompt"),
    path("chats/", include("chat.urls")),
    path("admin/", admin.site.urls),
]
