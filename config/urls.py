from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from audits.views import media

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Photos need a login, so other people on the same wifi cannot open them.
    path("media/<path:path>", media, name="media"),
    path("", include("audits.urls")),
]
