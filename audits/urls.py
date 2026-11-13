from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("audits/<int:pk>/item/", views.item_update, name="item_update"),
    path("audits/<int:pk>/zone-photo/<slug:zone>/", views.zone_photo, name="zone_photo"),
    path("audits/<int:pk>/ac-on/", views.ac_on, name="ac_on"),
    path("audits/<int:pk>/noise-inside/", views.noise_inside, name="noise_inside"),
    path("audits/<int:pk>/other/add/", views.add_other_item, name="add_other_item"),
    path("audits/<int:pk>/other/<int:item_pk>/delete/", views.delete_other_item, name="delete_other_item"),
    path("audits/<int:pk>/flooring/<int:item_pk>/", views.set_material, name="set_material"),
    path("audits/<int:pk>/<slug:step>/", views.audit_step, name="audit_step"),
    path("issues/", views.issue_list, name="issue_list"),
    path("issues/export.csv", views.issue_export, name="issue_export"),
    path("issues/<int:pk>/status/", views.issue_status, name="issue_status"),
    path("issues/<int:pk>/edit/", views.issue_edit, name="issue_edit"),
    path("dashboard/", views.dashboard, name="dashboard"),
]
