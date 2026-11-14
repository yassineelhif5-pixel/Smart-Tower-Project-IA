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
from configuration import audit
from configuration.models import AuditEvent
from configuration.views import PlatformView, int_param

from . import services
from .models import STATUSES, Tenant, TenantDomain
from .domain_utils import normalize_domain

User = get_user_model()


def tenant_row(t):
    return {
        "id": t.id, "slug": t.slug, "name": t.name, "status": t.status, "statusLabel": t.get_status_display(),
        "industry": t.industry, "website": t.website, "phone": t.phone, "address": t.address,
        "city": t.city, "country": t.country, "contactName": t.contact_name,
        "contactEmail": t.contact_email, "contactPhone": t.contact_phone, "description": t.description,
        "statusReason": t.status_reason, "statusChangedAt": t.status_changed_at, "language": t.language,
        "createdAt": t.created_at, "users": getattr(t, "user_count", None), "activeUsers": getattr(t, "active_user_count", None),
    }


def with_counts(qs):
    return qs.annotate(user_count=Count("users", distinct=True),
                       active_user_count=Count("users", filter=Q(users__is_active=True), distinct=True))


class CustomOfferSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    currency = serializers.CharField(max_length=3, required=False, default="EUR")
    billingPeriod = serializers.ChoiceField(choices=["month", "year", "once"], required=False, default="month")
    durationDays = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    trialDays = serializers.IntegerField(min_value=0, required=False, default=0)
    licenseModel = serializers.ChoiceField(choices=["named", "concurrent", "mixed"])
    maxUsers = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    namedLicenses = serializers.IntegerField(min_value=0, required=False, default=0)
    concurrentLicenses = serializers.IntegerField(min_value=0, required=False, default=0)
    maxSessionsPerUser = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    features = serializers.ListField(child=serializers.CharField(max_length=30), required=False, default=list)
    conditions = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        named, concurrent = attrs.get("namedLicenses", 0), attrs.get("concurrentLicenses", 0)
        model = attrs["licenseModel"]
        if named + concurrent < 1:
            raise serializers.ValidationError("Ajoutez au moins une licence nominative ou concurrente.")
        if model == "named" and concurrent:
            raise serializers.ValidationError({"concurrentLicenses": "Cette offre contient uniquement des licences nominatives."})
        if model == "concurrent" and named:
            raise serializers.ValidationError({"namedLicenses": "Cette offre contient uniquement des licences concurrentes."})
        return attrs


class TenantCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    slug = serializers.SlugField(max_length=50, required=False, allow_blank=True)
    adminUsername = serializers.RegexField(r"^[\w.@+-]+$", max_length=150)
    adminEmail = serializers.EmailField(required=False, allow_blank=True)
    adminFirstName = serializers.CharField(max_length=150, required=False, allow_blank=True)
    adminLastName = serializers.CharField(max_length=150, required=False, allow_blank=True)
    offerVersion = serializers.IntegerField(required=False, allow_null=True)
    customOffer = CustomOfferSerializer(required=False)
    contractReference = serializers.CharField(max_length=40, required=False, allow_blank=True)
    endDate = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        if attrs.get("offerVersion") and attrs.get("customOffer"):
            raise serializers.ValidationError("Choisissez une offre du catalogue ou une offre personnalisée, pas les deux.")
        return attrs


class TenantUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    status = serializers.ChoiceField(choices=[s for s, _ in STATUSES], required=False)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True)
    language = serializers.ChoiceField(choices=["fr", "en", "ar"], required=False)
    industry = serializers.CharField(max_length=120, required=False, allow_blank=True)
    website = serializers.URLField(max_length=255, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    address = serializers.CharField(max_length=200, required=False, allow_blank=True)
    city = serializers.CharField(max_length=120, required=False, allow_blank=True)
    country = serializers.CharField(max_length=80, required=False, allow_blank=True)
    contactName = serializers.CharField(max_length=150, required=False, allow_blank=True)
    contactEmail = serializers.EmailField(max_length=254, required=False, allow_blank=True)
    contactPhone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)


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
                custom_offer=d.get("customOffer"),
                contract_reference=d.get("contractReference", ""), end_date=d.get("endDate"))
        except services.TenantError as exc:
            raise ApiError("VALIDATION_ERROR", str(exc)) from exc
        row = tenant_row(with_counts(Tenant.objects.filter(pk=tenant.pk)).get())
        # Le mot de passe provisoire n'est affiché qu'une fois ; il devra être changé à la première connexion.
        return Response({**row, "admin": {"id": admin.id, "username": admin.username}, "temporaryPassword": password},
                        status=status.HTTP_201_CREATED)


class TenantDomainSerializer(serializers.Serializer):
    domain = serializers.CharField(max_length=253)
    tenant = serializers.IntegerField()
    enabled = serializers.BooleanField(required=False, default=True)
    client = serializers.CharField(max_length=20, required=False, allow_blank=True, allow_null=True)

    def validate_domain(self, value):
        try:
            return normalize_domain(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


def _domain_client(tenant, code):
    """Client de l'entreprise (ou None) ; refus si le client appartient à une autre entreprise."""
    if not code:
        return None
    from projects.models import Client
    client = Client.objects.filter(pk=code, tenant=tenant).first()
    if client is None:
        raise ApiError("VALIDATION_ERROR", "Ce client n'appartient pas à l'entreprise choisie.")
    return client


def domain_row(row, by=None):
    return {"id": row.pk, "domain": row.domain, "tenant": row.tenant_id, "tenantName": row.tenant.name,
            "client": row.client_id, "clientName": row.client.name if row.client_id else None, "enabled": row.enabled,
            "createdAt": row.created_at, "createdBy": by or (row.created_by.username if row.created_by else None)}


class PlatformDomainListView(PlatformView):
    def get(self, request):
        rows = TenantDomain.objects.select_related("tenant", "created_by", "client").all()
        return Response([domain_row(row) for row in rows])

    def post(self, request):
        serializer = TenantDomainSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tenant = get_object_or_404(Tenant, pk=data["tenant"])
        row = TenantDomain.objects.filter(domain=data["domain"]).first()
        if row and row.tenant_id != tenant.pk:
            raise ApiError("DOMAIN_ALREADY_ASSIGNED", "Ce domaine est déjà affecté à une autre entreprise.", status.HTTP_409_CONFLICT)
        client = _domain_client(tenant, data.get("client"))
        if row:
            row.enabled = data["enabled"]
            if "client" in data:
                row.client = client
            row.save(update_fields=["enabled", "client", "updated_at"])
            created = False
        else:
            row = TenantDomain.objects.create(domain=data["domain"], tenant=tenant, client=client, enabled=data["enabled"], created_by=request.user)
            created = True
        audit.record(request.user, f"Domaine {row.domain}", "Domaine attribué" if created else "Domaine activé",
                     "", tenant.name + (f" · client {client.name}" if client else ""), tenant=tenant)
        return Response(domain_row(row, request.user.username), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class PlatformDomainDetailView(PlatformView):
    def patch(self, request, pk):
        row = get_object_or_404(TenantDomain.objects.select_related("tenant"), pk=pk)
        serializer = TenantDomainSerializer(data={"domain": row.domain, **request.data}, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        old_tenant = row.tenant
        if "tenant" in data:
            row.tenant = get_object_or_404(Tenant, pk=data["tenant"])
        if "enabled" in data:
            row.enabled = data["enabled"]
        if "client" in request.data:
            row.client = _domain_client(row.tenant, data.get("client"))
        elif row.tenant_id != old_tenant.pk:
            row.client = None  # le client appartenait à l'ancienne entreprise
        row.save(update_fields=["tenant", "enabled", "client", "updated_at"])
        audit.record(request.user, f"Domaine {row.domain}", "Affectation du domaine modifiée",
                     f"{old_tenant.name} · {'actif' if not row.enabled else 'inactif'}",
                     f"{row.tenant.name} · {'actif' if row.enabled else 'inactif'}", tenant=row.tenant)
        return Response(domain_row(row))


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
        s = TenantUpdateSerializer(data=request.data, partial=True)
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
        fields = {"industry": "industry", "website": "website", "phone": "phone", "address": "address",
                  "city": "city", "country": "country", "contactName": "contact_name", "contactEmail": "contact_email",
                  "contactPhone": "contact_phone", "description": "description"}
        changed = []
        for external, field in fields.items():
            if external in d and getattr(tenant, field) != d[external]:
                setattr(tenant, field, d[external])
                changed.append(field)
        if changed:
            tenant.save(update_fields=changed)
            audit.record(request.user, f"Entreprise {tenant.name}", "Fiche entreprise modifiée", "", ", ".join(changed), tenant=None)
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
