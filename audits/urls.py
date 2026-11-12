from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("audits/<int:pk>/finding/", views.finding_update, name="finding_update"),
    path("audits/<int:pk>/zone-photo/<slug:zone>/", views.zone_photo, name="zone_photo"),
    path("audits/<int:pk>/noise-inside/", views.noise_inside, name="noise_inside"),
    path("audits/<int:pk>/decor/", views.add_decor, name="add_decor"),
    path("audits/<int:pk>/decor/<int:item_pk>/delete/", views.delete_decor, name="delete_decor"),
    path("audits/<int:pk>/flooring/<int:item_pk>/", views.set_material, name="set_material"),
    path("audits/<int:pk>/<slug:step>/", views.audit_step, name="audit_step"),
    path("issues/", views.issue_list, name="issue_list"),
    path("issues/export.csv", views.issue_export, name="issue_export"),
    path("issues/<int:pk>/status/", views.issue_status, name="issue_status"),
    path("issues/<int:pk>/edit/", views.issue_edit, name="issue_edit"),
    path("dashboard/", views.dashboard, name="dashboard"),
]
