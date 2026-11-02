"""API du Pilote : gestion des entreprises (tenants) et journal de la plateforme.

Le Pilote voit les informations administratives d'une entreprise (statut, comptes, compteurs), jamais
ses données métier privées (projets, tâches, documents…).
"""
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response

from config.errors import ApiError
from configuration.models import AuditEvent
from configuration.views import PlatformView, int_param

from . import services
from .models import STATUSES, Tenant

User = get_user_model()


def tenant_row(t):
    return {
        "id": t.id, "slug": t.slug, "name": t.name, "status": t.status, "statusLabel": t.get_status_display(),
        "statusReason": t.status_reason, "statusChangedAt": t.status_changed_at, "language": t.language,
        "createdAt": t.created_at, "users": getattr(t, "user_count", None), "activeUsers": getattr(t, "active_user_count", None),
    }


def with_counts(qs):
    return qs.annotate(user_count=Count("users", distinct=True),
                       active_user_count=Count("users", filter=Q(users__is_active=True), distinct=True))


class TenantCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    slug = serializers.SlugField(max_length=50, required=False, allow_blank=True)
    adminUsername = serializers.RegexField(r"^[\w.@+-]+$", max_length=150)
    adminEmail = serializers.EmailField(required=False, allow_blank=True)
    adminFirstName = serializers.CharField(max_length=150, required=False, allow_blank=True)
    adminLastName = serializers.CharField(max_length=150, required=False, allow_blank=True)
    offerVersion = serializers.IntegerField(required=False, allow_null=True)
    contractReference = serializers.CharField(max_length=40, required=False, allow_blank=True)
    endDate = serializers.DateField(required=False, allow_null=True)


class TenantUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    status = serializers.ChoiceField(choices=[s for s, _ in STATUSES], required=False)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True)
    language = serializers.ChoiceField(choices=["fr", "en", "ar"], required=False)


class TenantListView(PlatformView):
    def get(self, request):
        qs = with_counts(Tenant.objects.all())
        q, state = request.query_params.get("q", "").strip(), request.query_params.get("status", "")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(slug__icontains=q))
        if state:
            qs = qs.filter(status=state)
        return Response([tenant_row(t) for t in qs])

    def post(self, request):
        s = TenantCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        from licensing.models import OfferVersion
        version = get_object_or_404(OfferVersion, pk=d["offerVersion"]) if d.get("offerVersion") else None
        try:
            tenant, admin, password = services.create_tenant(
                by=request.user, name=d["name"], slug=d.get("slug"), admin_username=d["adminUsername"],
                admin_email=d.get("adminEmail", ""), admin_first_name=d.get("adminFirstName", ""),
                admin_last_name=d.get("adminLastName", ""), version=version,
                contract_reference=d.get("contractReference", ""), end_date=d.get("endDate"))
        except services.TenantError as exc:
            raise ApiError("VALIDATION_ERROR", str(exc)) from exc
        row = tenant_row(with_counts(Tenant.objects.filter(pk=tenant.pk)).get())
        # Le mot de passe provisoire n'est affiché qu'une fois ; il devra être changé à la première connexion.
        return Response({**row, "admin": {"id": admin.id, "username": admin.username}, "temporaryPassword": password},
                        status=status.HTTP_201_CREATED)


class TenantDetailView(PlatformView):
    def get(self, request, pk):
        tenant = get_object_or_404(with_counts(Tenant.objects.all()), pk=pk)
        users = User.objects.filter(tenant=tenant).select_related("role").order_by("username")
        return Response({
            **tenant_row(tenant),
            # Comptes : identité et rôle seulement, aucune donnée métier.
            "userList": [{"id": u.id, "username": u.username, "name": u.display_name, "role": u.role.label if u.role else None,
                          "isActive": u.is_active, "lastLogin": u.last_login} for u in users],
        })

    def patch(self, request, pk):
        tenant = get_object_or_404(Tenant, pk=pk)
        s = TenantUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        from configuration import audit
        if "name" in d and d["name"].strip() != tenant.name:
            before, tenant.name = tenant.name, d["name"].strip()
            tenant.save(update_fields=["name"])
            audit.record(request.user, f"Entreprise {tenant.name}", "Entreprise renommée", before, tenant.name, tenant=None)
        if "language" in d and d["language"] != tenant.language:
            before, tenant.language = tenant.language, d["language"]
            tenant.save(update_fields=["language"])
            audit.record(request.user, f"Entreprise {tenant.name}", "Langue modifiée", before, tenant.language, tenant=None)
        if "status" in d:
            try:
                services.change_status(by=request.user, tenant=tenant, status=d["status"], reason=d.get("reason", ""))
            except services.TenantError as exc:
                raise ApiError("VALIDATION_ERROR", str(exc)) from exc
        return self.get(request, pk)


class PlatformAuditView(PlatformView):
    """Journal de la plateforme : événements du Pilote et événements administratifs des tenants (pas le métier)."""

    def get(self, request):
        limit = int_param(request, "limit", 200, 1, 1000)
        rows = AuditEvent.objects.select_related("actor", "tenant")
        tenant = request.query_params.get("tenant")
        rows = rows.filter(tenant_id=tenant) if tenant else rows.filter(tenant__isnull=True)
        return Response([{"at": r.at, "actor": r.actor.username if r.actor else None, "tenant": r.tenant.name if r.tenant else None,
                          "entity": r.entity, "event": r.event, "old": r.old_value, "new": r.new_value, "trace": r.trace}
                         for r in rows[:limit]])
