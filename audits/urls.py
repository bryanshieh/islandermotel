from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("audits/<int:pk>/finding/", views.finding_update, name="finding_update"),
    path("audits/<int:pk>/decor/", views.add_decor, name="add_decor"),
    path("audits/<int:pk>/<slug:step>/", views.audit_step, name="audit_step"),
    path("issues/", views.issue_list, name="issue_list"),
    path("dashboard/", views.dashboard, name="dashboard"),
]
