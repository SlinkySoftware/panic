"""Authentication URL routes.

``/login`` (GET+POST) and ``/logout`` (POST) are gone (T-S6-06): superseded by the real JSON
contract at ``/api/v1/auth/{providers,csrf,login,logout}`` (``panic_server.api.urls``), which
T-S6-04 flagged this JSON stopgap as waiting on. The OIDC routes are untouched.
"""

from __future__ import annotations

from django.urls import path

from panic_server.auth import views

urlpatterns = [
    path("auth/oidc/login", views.oidc_login_view, name="oidc_login"),
    path("auth/oidc/callback", views.oidc_callback_view, name="oidc_callback"),
]
