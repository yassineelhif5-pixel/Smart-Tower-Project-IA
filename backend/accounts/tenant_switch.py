"""Accès multi-entreprises : un utilisateur (ex. chef de projet d'une ESN) peut travailler pour plusieurs clients / tenants
et basculer de l'un à l'autre. L'accès à une entreprise est accordé par un administrateur de CETTE entreprise."""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit

from .models import Role, TenantMembership


def ensure_home_membership(user):
    """L'entreprise actuelle de l'utilisateur est toujours dans ses accès (pour pouvoir y revenir)."""
    if user.tenant_id:
        TenantMembership.objects.get_or_create(user=user, tenant_id=user.tenant_id,
                                               defaults={"role_id": user.role_id, "client_id": user.client_id})


def blocked_reason(tenant):
    """Pourquoi on ne peut pas travailler sur cette entreprise (suspendue, abonnement expiré…), ou None."""
    if tenant.status != "active":
        return "Entreprise suspendue"
    from licensing import services
    problem = services.subscription_problem(tenant)
    return problem.message if problem else None


def _row(tenant, current, role):
    why = None if current else blocked_reason(tenant)
    return {"id": tenant.pk, "slug": tenant.slug, "name": tenant.name, "current": current,
            "role": role.label if role else None, "active": why is None, "reason": why}


def tenants_of(user):
    rows = list(TenantMembership.objects.filter(user=user).select_related("tenant", "role"))
    if rows and user.tenant_id and not any(m.tenant_id == user.tenant_id for m in rows):
        ensure_home_membership(user)  # l'entreprise d'origine reste accessible
        rows = list(TenantMembership.objects.filter(user=user).select_related("tenant", "role"))
    if not rows:
        return [_row(user.tenant, True, user.role if user.role_id else None)] if user.tenant_id else []
    return [_row(m.tenant, m.tenant_id == user.tenant_id, m.role if m.role_id else None) for m in rows]


class SwitchTenantView(APIView):
    """POST {tenant} : bascule l'utilisateur sur une autre entreprise à laquelle il a accès."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({"tenants": tenants_of(request.user)})

    def post(self, request):
        user = request.user
        target = request.data.get("tenant")
        m = TenantMembership.objects.filter(user=user, tenant_id=target).select_related("tenant").first()
        if m is None:
            raise ApiError("FORBIDDEN_PERMISSION", "Vous n'avez pas accès à cette entreprise.", status.HTTP_403_FORBIDDEN)
        if m.tenant_id == user.tenant_id:
            return Response({"tenant": m.tenant.name})
        why = blocked_reason(m.tenant)
        if why:
            raise ApiError("FORBIDDEN_PERMISSION", f"Impossible d'ouvrir « {m.tenant.name} » : {why}", status.HTTP_403_FORBIDDEN)
        from licensing import services as lic
        key = request.session.session_key
        prev = (user.tenant_id, user.role_id, user.client_id)
        old = user.tenant.name if user.tenant_id else "—"
        with transaction.atomic():
            ensure_home_membership(user)
            # Le profil et le client courants sont mémorisés pour l'entreprise quittée.
            TenantMembership.objects.filter(user=user, tenant_id=user.tenant_id).update(role_id=user.role_id, client_id=user.client_id)
            user.tenant_id, user.role_id, user.client_id = m.tenant_id, m.role_id, m.client_id
            user.save(update_fields=["tenant", "role", "client"])
            m.last_used_at = timezone.now()
            m.save(update_fields=["last_used_at"])
        # La licence (session concurrente) de l'entreprise quittée est libérée, une licence est prise dans la nouvelle.
        if key:
            user.tenant_id = prev[0]
            lic.close_user_session(user, key, "switch")
            user.tenant_id = m.tenant_id
            user = get_user_model().objects.select_related("tenant").get(pk=user.pk)
            try:
                lic.open_session(user, key)
            except lic.LicenseError as e:
                # Pas de licence disponible : on revient dans l'entreprise d'origine.
                user.tenant_id, user.role_id, user.client_id = prev
                user.save(update_fields=["tenant", "role", "client"])
                user = get_user_model().objects.select_related("tenant").get(pk=user.pk)
                try:
                    lic.open_session(user, key)
                except lic.LicenseError:
                    pass
                raise ApiError(e.code, e.message, e.http_status)
        audit.record(user, f"Utilisateur {user.username}", "Changement d'entreprise", old, m.tenant.name, tenant=m.tenant)
        return Response({"tenant": m.tenant.name})


class TenantGuestsView(APIView):
    """Administrateur : utilisateurs d'autres entreprises ayant accès à SON entreprise (ajout / retrait)."""

    permission_classes = [permissions.IsAuthenticated]

    def _check(self, request):
        if not (request.user.is_app_admin and request.user.tenant_id):
            raise ApiError("FORBIDDEN_PERMISSION", "Réservé à l'administrateur de l'entreprise.", status.HTTP_403_FORBIDDEN)

    def get(self, request):
        self._check(request)
        rows = TenantMembership.objects.filter(tenant_id=request.user.tenant_id).exclude(user__tenant_id=request.user.tenant_id) \
            .select_related("user", "role", "user__tenant")
        # On liste aussi les invités actuellement « basculés » chez nous dont l'entreprise d'origine est ailleurs.
        out = [{"id": m.pk, "user": m.user.display_name, "email": m.user.email, "username": m.user.username,
                "home": m.user.tenant.name if m.user.tenant_id else "—", "role": m.role.label if m.role_id else None,
                "roleCode": m.role_id, "since": m.created_at, "lastUsed": m.last_used_at} for m in rows]
        roles = [{"code": r.code, "label": r.label} for r in Role.objects.filter(tenant__isnull=True).order_by("position")
                 if r.code not in ("support",)]
        return Response({"guests": out, "roles": roles})

    def post(self, request):
        """Donne accès à un utilisateur existant (identifiant ou e-mail) d'une autre entreprise."""
        self._check(request)
        who = str(request.data.get("user") or "").strip()
        role = get_object_or_404(Role, code=request.data.get("role") or "cdp")
        User = get_user_model()
        user = User.objects.filter(email__iexact=who).first() or User.objects.filter(username__iexact=who).first()
        if user is None:
            raise ApiError("VALIDATION_ERROR", "Aucun utilisateur ne correspond à cet identifiant ou cet e-mail.")
        if user.is_platform_admin:
            raise ApiError("VALIDATION_ERROR", "Le Pilote de la plateforme n'a pas besoin d'accès.")
        if user.tenant_id == request.user.tenant_id:
            raise ApiError("VALIDATION_ERROR", "Cet utilisateur appartient déjà à votre entreprise.")
        ensure_home_membership(user)
        m, created = TenantMembership.objects.update_or_create(user=user, tenant_id=request.user.tenant_id,
                                                                defaults={"role": role, "granted_by": request.user})
        audit.record(request.user, f"Utilisateur {user.username}", "Accès invité accordé" if created else "Accès invité modifié", "",
                     f"{role.label}", tenant=request.user.tenant)
        return self.get(request)

    def delete(self, request, mid):
        self._check(request)
        m = get_object_or_404(TenantMembership, pk=mid, tenant_id=request.user.tenant_id)
        if m.user.tenant_id == request.user.tenant_id:
            # L'invité est en ce moment sur notre entreprise : on le renvoie dans son entreprise d'origine.
            home = TenantMembership.objects.filter(user=m.user).exclude(pk=m.pk).select_related("tenant").first()
            if home is None:
                raise ApiError("VALIDATION_ERROR", "Impossible de retirer l'accès : c'est la seule entreprise de cet utilisateur.")
            u = m.user
            u.tenant_id, u.role_id, u.client_id = home.tenant_id, home.role_id, home.client_id
            u.save(update_fields=["tenant", "role", "client"])
        audit.record(request.user, f"Utilisateur {m.user.username}", "Accès invité retiré", m.role.label if m.role_id else "", "",
                     tenant=request.user.tenant)
        m.delete()
        return self.get(request)
