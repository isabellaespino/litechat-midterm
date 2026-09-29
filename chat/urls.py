from django.urls import path

from . import views

urlpatterns = [
    path("", views.chat_list, name="chat_list"),
    path("new/", views.chat_new, name="chat_new"),
    path("<int:pk>/", views.chat_detail, name="chat_detail"),
    path("<int:pk>/rename/", views.chat_rename, name="chat_rename"),
    path("<int:pk>/delete/", views.chat_delete, name="chat_delete"),
    path("<int:pk>/title/", views.chat_title, name="chat_title"),
]
