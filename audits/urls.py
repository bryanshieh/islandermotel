from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("issues/", views.issue_list, name="issue_list"),
    path("dashboard/", views.dashboard, name="dashboard"),
]
