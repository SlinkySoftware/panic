"""DRF serializers for the T-S6-06 endpoints: request validation (login) and OpenAPI response
shapes (everything else -- the views return plain dicts built by ``panic_server.services``;
these classes exist so drf-spectacular has a concrete schema to generate instead of guessing).
"""

from __future__ import annotations

from rest_framework import serializers

# ---------------------------------------------------------------- requests


class LoginRequestSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=512, trim_whitespace=False, style={"input_type": "password"})


# ---------------------------------------------------------------- shared shapes


class OidcProviderSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    provider_name = serializers.CharField()


class ProvidersResponseSerializer(serializers.Serializer):
    instance_name = serializers.CharField()
    local_enabled = serializers.BooleanField()
    ldap_enabled = serializers.BooleanField()
    oidc = OidcProviderSerializer()


class PrefsSerializer(serializers.Serializer):
    density = serializers.CharField()
    theme = serializers.CharField()
    unreachable_policy = serializers.CharField()


class ProfileSerializer(serializers.Serializer):
    """``me``/``real_user`` (API.md §4.1/§4.2): a user's own profile, as seen by themselves."""

    id = serializers.CharField()
    username = serializers.CharField()
    display_name = serializers.CharField()
    auth_source = serializers.CharField()
    prefs = PrefsSerializer()


class SubjectSerializer(serializers.Serializer):
    """The smaller shape used for the ``view_as`` subject."""

    id = serializers.CharField()
    username = serializers.CharField()
    display_name = serializers.CharField()


class LoginResponseSerializer(serializers.Serializer):
    me = ProfileSerializer()


class LaunchSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["OPEN", "COPY", "DOWNLOAD"])
    url = serializers.CharField(required=False)
    command = serializers.CharField(required=False)
    uri = serializers.CharField(required=False)
    href = serializers.CharField(required=False)


class ItemViewSerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    protocol = serializers.CharField()
    target = serializers.CharField()
    site = serializers.CharField()
    scope = serializers.CharField()
    zone_names = serializers.ListField(child=serializers.CharField())
    tags = serializers.ListField(child=serializers.CharField())
    reachable = serializers.BooleanField()
    unreachable_reason = serializers.CharField(allow_null=True)
    launch = LaunchSerializer()


# ---------------------------------------------------------------- bootstrap


class PermissionsSerializer(serializers.Serializer):
    global_admin = serializers.BooleanField()
    can_add_global = serializers.BooleanField()
    can_add_team = serializers.BooleanField()
    can_view_as = serializers.BooleanField()


class ZoneRefSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()


class ClientSerializer(serializers.Serializer):
    ip = serializers.CharField()
    zone = ZoneRefSerializer(allow_null=True)
    zone_source = serializers.ChoiceField(choices=["CIDR", "DEFAULT"])


class NavDashboardSerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    default = serializers.BooleanField()
    locked = serializers.BooleanField()


class NavSerializer(serializers.Serializer):
    dashboards = NavDashboardSerializer(many=True)


class DefaultDashboardSerializer(serializers.Serializer):
    id = serializers.CharField()
    source = serializers.ChoiceField(choices=["USER", "SYSTEM_GLOBAL", "FALLBACK"])


class InstanceSerializer(serializers.Serializer):
    name = serializers.CharField()
    version = serializers.CharField()


class BootstrapResponseSerializer(serializers.Serializer):
    instance = InstanceSerializer()
    me = ProfileSerializer(allow_null=True)
    real_user = ProfileSerializer(allow_null=True)
    view_as = SubjectSerializer(allow_null=True)
    permissions = PermissionsSerializer()
    client = ClientSerializer()
    nav = NavSerializer()
    default_dashboard = DefaultDashboardSerializer(allow_null=True)


# ---------------------------------------------------------------- dashboard view


class WidgetSerializer(serializers.Serializer):
    id = serializers.CharField()
    widget_type = serializers.ChoiceField(choices=["HOST", "LIST"])
    title = serializers.CharField()
    grid_x = serializers.IntegerField()
    grid_y = serializers.IntegerField()
    grid_w = serializers.IntegerField()
    grid_h = serializers.IntegerField()
    catalog_item_id = serializers.CharField(allow_null=True)
    list_id = serializers.CharField(allow_null=True)


class DashboardPropsSerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()
    scope = serializers.CharField()
    team_ids = serializers.ListField(child=serializers.CharField())
    owner_usernames = serializers.ListField(child=serializers.CharField())
    always_display = serializers.BooleanField()
    version = serializers.IntegerField()
    can_edit = serializers.BooleanField()
    is_user_default = serializers.BooleanField()
    is_global_default = serializers.BooleanField()


class ListSummarySerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    scope = serializers.CharField()
    item_count = serializers.IntegerField()
    item_ids = serializers.ListField(child=serializers.CharField())
    truncated = serializers.BooleanField()


class UnavailableSerializer(serializers.Serializer):
    items = serializers.ListField(child=serializers.CharField())
    lists = serializers.ListField(child=serializers.CharField())


class DashboardViewResponseSerializer(serializers.Serializer):
    dashboard = DashboardPropsSerializer()
    widgets = WidgetSerializer(many=True)
    items = serializers.DictField(child=ItemViewSerializer())
    lists = serializers.DictField(child=ListSummarySerializer())
    unavailable = UnavailableSerializer()


# ---------------------------------------------------------------- search


class SearchResultSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["DASHBOARD", "ITEM", "LIST"])
    id = serializers.CharField()
    title = serializers.CharField()
    subtitle = serializers.CharField()
    item = ItemViewSerializer(allow_null=True)


class SearchResponseSerializer(serializers.Serializer):
    results = SearchResultSerializer(many=True)


# ---------------------------------------------------------------- errors


class ErrorSerializer(serializers.Serializer):
    error_code = serializers.CharField()
    detail = serializers.CharField()


__all__ = [
    "BootstrapResponseSerializer",
    "ClientSerializer",
    "DashboardPropsSerializer",
    "DashboardViewResponseSerializer",
    "DefaultDashboardSerializer",
    "ErrorSerializer",
    "InstanceSerializer",
    "ItemViewSerializer",
    "LaunchSerializer",
    "ListSummarySerializer",
    "LoginRequestSerializer",
    "LoginResponseSerializer",
    "NavDashboardSerializer",
    "NavSerializer",
    "OidcProviderSerializer",
    "PermissionsSerializer",
    "PrefsSerializer",
    "ProfileSerializer",
    "ProvidersResponseSerializer",
    "SearchResponseSerializer",
    "SearchResultSerializer",
    "SubjectSerializer",
    "UnavailableSerializer",
    "WidgetSerializer",
    "ZoneRefSerializer",
]
