from django.contrib import admin
from django.urls import include, path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("accounts/", include("accounts.urls")),
    path("models/", include("catalog.urls")),
    path("admin/", admin.site.urls),
]
