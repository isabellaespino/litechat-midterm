from django.urls import path

from . import views

urlpatterns = [
    path("", views.chat_list, name="chat_list"),
    path("new/", views.chat_new, name="chat_new"),
    path("<int:pk>/", views.chat_detail, name="chat_detail"),
]
