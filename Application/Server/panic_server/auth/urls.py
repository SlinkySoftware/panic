"""Authentication URL routes (OIDC only).

Local sign-in and sign-out are the JSON contract at ``/api/v1/auth/{providers,csrf,login,logout}``
(``panic_server.api.urls``).
"""

from __future__ import annotations

from django.urls import path

from panic_server.auth import views

urlpatterns = [
    path("auth/oidc/login", views.oidc_login_view, name="oidc_login"),
    path("auth/oidc/callback", views.oidc_callback_view, name="oidc_callback"),
]
