from django.urls import path

from . import views

urlpatterns = [
    path("", views.credit, name="credit"),
]
