"""Module « Import Excel des projets et des actions » : autorisé par profil.

- Le Pilote active ou non le module pour une entreprise (réglage « excel_import_enabled », activé par défaut).
- L'administrateur de l'entreprise (ou le Pilote) choisit les profils qui voient l'option (« excel_import_profiles »).
- L'administrateur garde toujours l'accès tant que le Pilote n'a pas désactivé le module.
"""
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit
from configuration.models import AppSetting

ENABLED_KEY, PROFILES_KEY = "excel_import_enabled", "excel_import_profiles"
DEFAULT_PROFILES = ["cdp"]


def _get(tenant, key, default):
    row = AppSetting.objects.filter(tenant=tenant, key=key).first()
    return row.value if row is not None else default


def enabled_for_tenant(tenant):
    return bool(_get(tenant, ENABLED_KEY, True))


def profiles(tenant):
    v = _get(tenant, PROFILES_KEY, None)
    return list(v) if isinstance(v, list) else list(DEFAULT_PROFILES)


def can_import(user):
    if not user or not user.tenant_id or not enabled_for_tenant(user.tenant):
        return False
    return bool(user.is_app_admin or (user.role_id and user.role_id in profiles(user.tenant)))


def _out(tenant):
    from accounts.models import Role
    return {"enabled": enabled_for_tenant(tenant), "profiles": profiles(tenant),
            "roles": [{"code": r.code, "label": r.label, "internal": r.internal} for r in
                      Role.objects.filter(Q(tenant__isnull=True) | Q(tenant=tenant)).exclude(code__in=["superadmin", "admin"]).order_by("label")]}


def _save(tenant, data, by, pilot=False):
    if "profiles" in data:
        vals = data.get("profiles")
        if not isinstance(vals, list):
            raise ApiError("VALIDATION_ERROR", "Liste de profils attendue.")
        AppSetting.objects.update_or_create(tenant=tenant, key=PROFILES_KEY, defaults={"value": [str(v)[:20] for v in vals]})
    if pilot and "enabled" in data:
        AppSetting.objects.update_or_create(tenant=tenant, key=ENABLED_KEY, defaults={"value": bool(data["enabled"])})
    audit.record(by, "Import Excel", "Accès au module d'import Excel", "", str({k: data[k] for k in ("enabled", "profiles") if k in data}), tenant=tenant)
    return _out(tenant)


class ExcelImportProfilesView(APIView):
    """Administrateur : GET / PUT {profiles} (le module doit être activé par le Pilote)."""

    def get(self, request):
        if not request.user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur.", status.HTTP_403_FORBIDDEN)
        return Response(_out(request.user.tenant))

    def put(self, request):
        if not request.user.is_app_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur.", status.HTTP_403_FORBIDDEN)
        if not enabled_for_tenant(request.user.tenant):
            raise ApiError("FORBIDDEN_PERMISSION", "Le module d'import Excel est désactivé par le Pilote pour votre entreprise.", status.HTTP_403_FORBIDDEN)
        return Response(_save(request.user.tenant, {"profiles": request.data.get("profiles")}, request.user))


class PilotExcelImportView(APIView):
    """Pilote : GET / PUT {enabled, profiles} pour une entreprise."""

    def get(self, request, tenant_id):
        from tenants.models import Tenant
        if not request.user.is_platform_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au Pilote.", status.HTTP_403_FORBIDDEN)
        return Response(_out(get_object_or_404(Tenant, pk=tenant_id)))

    def put(self, request, tenant_id):
        from tenants.models import Tenant
        if not request.user.is_platform_admin:
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé au Pilote.", status.HTTP_403_FORBIDDEN)
        return Response(_save(get_object_or_404(Tenant, pk=tenant_id), request.data, request.user, pilot=True))
