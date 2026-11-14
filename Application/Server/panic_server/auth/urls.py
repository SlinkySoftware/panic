"""Authentication URL routes."""

from __future__ import annotations

from django.urls import path

from panic_server.auth import views

urlpatterns = [
    path("login", views.login_view, name="login"),
    path("logout", views.logout_view, name="logout"),
    path("auth/oidc/login", views.oidc_login_view, name="oidc_login"),
    path("auth/oidc/callback", views.oidc_callback_view, name="oidc_callback"),
]
