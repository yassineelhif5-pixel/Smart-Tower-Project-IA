"""Paiement en ligne des offres et des licences avec Stripe Checkout (API REST, sans SDK).

Parcours : l'utilisateur (admin d'entreprise, admin d'une démo terminée) ou le Pilote (après validation d'une
demande) choisit une offre publiée ou un nombre de licences, puis est redirigé vers Stripe. Une fois le paiement
confirmé (retour de Stripe ou webhook), l'offre est activée ou les licences ajoutées automatiquement.
Les montants sont toujours calculés côté serveur à partir des offres et des prix configurés par le Pilote.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import requests
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import status

from accounts.models import PLATFORM_ROLE
from config.errors import ApiError
from configuration import audit
from configuration.models import Notification

from . import models as L

logger = logging.getLogger(__name__)
User = get_user_model()
API = "https://api.stripe.com/v1"
SETTING_KEY = "stripe"
CUSTOM_OFFER = "entreprise-sur-mesure"  # abonnement « Entreprise » : nombre de licences au choix
INTERVALS = {"month": "month", "year": "year", "once": ""}
INTERVAL_LABEL = {"month": "par mois", "year": "par an", "": "paiement unique"}


# --------------------------------------------------------------------------- configuration (Pilote)
def _row():
    from configuration.models import PlatformSetting
    return PlatformSetting.objects.filter(key=SETTING_KEY).select_related("updated_by").first()


def _dec(value, default="0"):
    try:
        return Decimal(str(value if value not in (None, "") else default))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def config(with_secrets=False):
    from configuration import crypto
    row = _row()
    v = dict(row.value or {}) if row else {}

    def secret(name, env):
        raw = v.get(name)
        if raw:
            try:
                return crypto.decrypt(raw), "pilot"
            except Exception:  # noqa: BLE001
                return "", ""
        value = os.environ.get(env, "").strip()
        return value, ("env" if value else "")

    key, key_src = secret("secret_key", "STRIPE_SECRET_KEY")
    hook, _ = secret("webhook_secret", "STRIPE_WEBHOOK_SECRET")
    out = {
        "enabled": bool(key) and v.get("enabled", True) is not False,
        "source": key_src,
        "mode": "live" if key.startswith(("sk_live", "rk_live")) else ("test" if key else ""),
        "hasSecretKey": bool(key), "secretHint": key[-4:] if key else "",
        "hasWebhookSecret": bool(hook),
        "publishableKey": v.get("publishable_key", ""),
        "currency": (v.get("currency") or "EUR").upper(),
        "namedPrice": str(_dec(v.get("named_price"), "0")),
        "concurrentPrice": str(_dec(v.get("concurrent_price"), "0")),
        "licenseInterval": v.get("license_interval") if v.get("license_interval") in INTERVALS else "month",
        "updatedAt": row.updated_at if row else None,
        "updatedBy": row.updated_by.display_name if row and row.updated_by_id else "",
    }
    if with_secrets:
        out["secretKey"], out["webhookSecret"] = key, hook
    return out


def save_config(by, data):
    from configuration import crypto
    from configuration.models import PlatformSetting
    row, _ = PlatformSetting.objects.get_or_create(key=SETTING_KEY)
    if data.get("reset"):
        row.value = {}
    else:
        v = dict(row.value or {})
        for field, name in (("secretKey", "secret_key"), ("webhookSecret", "webhook_secret")):
            raw = str(data.get(field) or "").strip()
            if raw:
                if field == "secretKey" and not raw.startswith(("sk_", "rk_")):
                    raise ApiError("VALIDATION_ERROR", "La clé secrète Stripe commence par « sk_test_ », « sk_live_ » ou « rk_ ».")
                if field == "webhookSecret" and not raw.startswith("whsec_"):
                    raise ApiError("VALIDATION_ERROR", "Le secret de signature du webhook commence par « whsec_ ».")
                v[name] = crypto.encrypt(raw)
        pk = str(data.get("publishableKey") or "").strip()
        if pk and not pk.startswith("pk_"):
            raise ApiError("VALIDATION_ERROR", "La clé publiable Stripe commence par « pk_ ».")
        v["publishable_key"] = pk
        currency = str(data.get("currency") or "EUR").strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ApiError("VALIDATION_ERROR", "Devise invalide (ex. EUR).")
        v["currency"] = currency
        for field, name in (("namedPrice", "named_price"), ("concurrentPrice", "concurrent_price")):
            price = _dec(data.get(field), "0")
            if price < 0 or price > 100000:
                raise ApiError("VALIDATION_ERROR", "Prix unitaire de licence invalide.")
            v[name] = str(price)
        interval = data.get("licenseInterval", "month")
        v["license_interval"] = interval if interval in INTERVALS else "month"
        v["enabled"] = data.get("enabled", True) is not False
        row.value = v
    row.updated_by = by
    row.save()
    audit.record(by, "Configuration de la plateforme", "Paiement Stripe modifié", "",
                 "réinitialisé" if data.get("reset") else ("activé" if row.value.get("enabled") else "désactivé"), tenant=None)


# --------------------------------------------------------------------------- appels Stripe
def _flatten(data, prefix=""):
    out = []
    for key, value in data.items():
        name = f"{prefix}[{key}]" if prefix else key
        if isinstance(value, dict):
            out += _flatten(value, name)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    out += _flatten(item, f"{name}[{i}]")
                else:
                    out.append((f"{name}[{i}]", item))
        elif value is not None:
            out.append((name, "true" if value is True else "false" if value is False else str(value)))
    return out


def _stripe(method, path, data=None):
    conf = config(with_secrets=True)
    if not conf["enabled"]:
        raise ApiError("PAYMENT_UNAVAILABLE", "Le paiement en ligne n'est pas encore activé par le Pilote.", status.HTTP_409_CONFLICT)
    try:
        resp = requests.request(method, f"{API}{path}", auth=(conf["secretKey"], ""), timeout=15,
                                data=_flatten(data) if data else None, headers={"Stripe-Version": "2024-06-20"})
        body = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise ApiError("PAYMENT_ERROR", "Stripe est injoignable pour le moment. Réessayez dans quelques instants.",
                       status.HTTP_502_BAD_GATEWAY) from exc
    if resp.status_code >= 400:
        msg = (body.get("error") or {}).get("message", "Erreur Stripe")
        logger.warning("Stripe %s %s : %s", method, path, msg)
        raise ApiError("PAYMENT_ERROR", f"Stripe a refusé l'opération : {msg}", status.HTTP_502_BAD_GATEWAY)
    return body


# --------------------------------------------------------------------------- devis
def _cents(amount):
    return int((_dec(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def offer_row(v):
    interval = INTERVALS.get(v.billing_period, "month")
    payable = v.price is not None and v.price > 0
    return {"id": v.pk, "offer": v.offer.name, "description": v.offer.description, "number": v.number,
            "price": str(v.price) if v.price is not None else None, "currency": v.currency, "interval": interval,
            "intervalLabel": INTERVAL_LABEL[interval], "maxUsers": v.max_users, "named": v.named_licenses,
            "concurrent": v.concurrent_licenses, "features": v.features or [], "payable": payable}


def custom_version(quantity, unit_price, interval):
    """Version de l'offre « Entreprise (sur mesure) » correspondant au nombre de licences choisi (créée au besoin)."""
    offer, _ = L.Offer.objects.get_or_create(code=CUSTOM_OFFER, defaults={
        "name": "Entreprise (sur mesure)", "position": 99,
        "description": "Abonnement sur mesure : le nombre de licences nominatives de votre choix, tous les modules."})
    if not offer.is_active:
        raise ApiError("VALIDATION_ERROR", "L'abonnement sur mesure est désactivé par le Pilote.")
    period = {"month": "month", "year": "year", "": "once"}[interval]
    price = (unit_price * quantity).quantize(Decimal("0.01"))
    version = (L.OfferVersion.objects.filter(offer=offer, is_published=True, named_licenses=quantity, price=price,
                                             billing_period=period).order_by("-number").first())
    if version is None:
        number = (L.OfferVersion.objects.filter(offer=offer).order_by("-number").values_list("number", flat=True).first() or 0) + 1
        version = L.OfferVersion.objects.create(
            offer=offer, number=number, is_published=True, price=price, billing_period=period, license_model="named",
            max_users=quantity, named_licenses=quantity, concurrent_licenses=0, features=[], limits={},
            conditions=f"Abonnement sur mesure : {quantity} licence(s) nominative(s).")
    return version


def options(tenant, request_obj=None):
    from accounts.signup import DEMO_OFFER
    from . import services as lic
    conf = config()
    sub = lic.current_subscription(tenant)
    versions = (L.OfferVersion.objects.filter(is_published=True, offer__is_active=True).exclude(offer__code__in=[DEMO_OFFER, "demo", CUSTOM_OFFER])
                .select_related("offer").order_by("offer__position", "offer__name", "-number"))
    seen, offers = set(), []
    for v in versions:
        if v.offer_id in seen:
            continue
        seen.add(v.offer_id)
        offers.append(offer_row(v))
    preselect = None
    if request_obj is not None:
        if request_obj.kind == "offer" and request_obj.target_version_id:
            preselect = {"mode": "offer", "versionId": request_obj.target_version_id}
            if not any(o["id"] == request_obj.target_version_id for o in offers):
                offers.insert(0, offer_row(request_obj.target_version))
        elif request_obj.kind in (L.NAMED, L.CONCURRENT):
            preselect = {"mode": "licenses", "licenseKind": request_obj.kind,
                         "quantity": request_obj.quantity_granted or request_obj.quantity or 1}
    interval = INTERVALS[conf["licenseInterval"]]
    recent = L.Payment.objects.filter(tenant=tenant).select_related("offer_version__offer")[:10]
    return {
        "configured": conf["enabled"], "mode": conf["mode"], "currency": conf["currency"],
        "tenant": {"id": tenant.pk, "name": tenant.name, "demo": bool(tenant.demo_until)},
        "current": ({"offer": sub.offer_version.offer.name, "version": sub.offer_version.number, "status": sub.get_status_display(),
                     "endDate": sub.end_date, "demo": sub.offer_version.offer.code == DEMO_OFFER} if sub else None),
        "offers": offers,
        "licensePrices": {"named": conf["namedPrice"], "concurrent": conf["concurrentPrice"], "interval": interval,
                          "intervalLabel": INTERVAL_LABEL[interval]},
        "canBuyLicenses": bool(sub) and sub.offer_version.offer.code not in (DEMO_OFFER, CUSTOM_OFFER),
        "custom": {"available": _dec(conf["namedPrice"]) > 0, "unit": conf["namedPrice"], "interval": interval,
                   "intervalLabel": INTERVAL_LABEL[interval]},
        "preselect": preselect,
        "request": {"id": request_obj.pk, "status": request_obj.status, "kind": request_obj.get_kind_display()} if request_obj else None,
        "payments": [payment_row(p) for p in recent],
    }


def payment_row(p):
    return {"id": p.pk, "tenant": p.tenant.name, "kind": p.kind,
            "label": (f"Entreprise (sur mesure) · {p.quantity} licence(s)" if p.offer_version_id and p.offer_version.offer.code == CUSTOM_OFFER
                      else f"{p.offer_version.offer.name} v{p.offer_version.number}" if p.offer_version_id
                      else f"{p.quantity} licence(s) {dict(L.LICENSE_KINDS).get(p.license_kind, '').lower()}(s)"),
            "amount": f"{p.amount / 100:.2f}", "currency": p.currency, "interval": p.interval, "status": p.status,
            "statusLabel": p.get_status_display(), "createdAt": p.created_at, "paidAt": p.paid_at, "appliedAt": p.applied_at,
            "error": p.error, "requestId": p.request_id, "checkoutUrl": p.checkout_url if p.status == L.Payment.PENDING else "",
            "by": p.created_by.display_name if p.created_by_id else ""}


# --------------------------------------------------------------------------- paiement
def checkout(*, by, tenant, base_url, mode, version_id=None, license_kind="", quantity=1, request_obj=None):
    from accounts.signup import DEMO_OFFER
    from . import services as lic
    conf = config()
    if not conf["enabled"]:
        raise ApiError("PAYMENT_UNAVAILABLE", "Le paiement en ligne n'est pas encore activé par le Pilote.", status.HTTP_409_CONFLICT)
    if tenant.status != "active":
        raise ApiError("TENANT_INACTIVE", "L'entreprise est suspendue : contactez le Pilote.", status.HTTP_403_FORBIDDEN)
    currency = conf["currency"]
    if mode == "offer":
        version = L.OfferVersion.objects.select_related("offer").filter(pk=version_id, is_published=True, offer__is_active=True).first()
        if version is None or version.offer.code in (DEMO_OFFER, "demo", CUSTOM_OFFER):
            raise ApiError("VALIDATION_ERROR", "Choisissez une offre publiée.")
        if version.price is None or version.price <= 0:
            raise ApiError("VALIDATION_ERROR", "Cette offre est sur devis : elle ne peut pas être payée en ligne. Contactez le Pilote.")
        unit, qty, interval = _cents(version.price), 1, INTERVALS.get(version.billing_period, "month")
        currency = (version.currency or currency).upper()
        name = f"Control Tower · {version.offer.name} (v{version.number})"
        kind, lkind = "offer", ""
    elif mode == "licenses":
        if license_kind not in (L.NAMED, L.CONCURRENT):
            raise ApiError("VALIDATION_ERROR", "Choisissez le type de licence.")
        try:
            qty = int(quantity)
        except (TypeError, ValueError):
            qty = 0
        if qty < 1 or qty > 1000:
            raise ApiError("VALIDATION_ERROR", "Indiquez un nombre de licences entre 1 et 1 000.")
        sub = lic.current_subscription(tenant)
        if sub is None or sub.offer_version.offer.code == DEMO_OFFER:
            raise ApiError("VALIDATION_ERROR", "Choisissez d'abord une offre : des licences supplémentaires s'ajoutent à un abonnement en cours.")
        price = _dec(conf["namedPrice"] if license_kind == L.NAMED else conf["concurrentPrice"])
        if price <= 0:
            raise ApiError("VALIDATION_ERROR", "Le prix des licences n'est pas encore défini par le Pilote.")
        unit, interval, version = _cents(price), INTERVALS[conf["licenseInterval"]], None
        name = f"Control Tower · licence {'nominative' if license_kind == L.NAMED else 'concurrente'}"
        kind, lkind = "licenses", license_kind
    elif mode == "custom":
        try:
            qty = int(quantity)
        except (TypeError, ValueError):
            qty = 0
        if qty < 1 or qty > 1000:
            raise ApiError("VALIDATION_ERROR", "Indiquez un nombre de licences entre 1 et 1 000.")
        price = _dec(conf["namedPrice"])
        if price <= 0:
            raise ApiError("VALIDATION_ERROR", "Le prix des licences n'est pas encore défini par le Pilote.")
        interval = INTERVALS[conf["licenseInterval"]]
        version = custom_version(qty, price, interval)
        # Une seule ligne Stripe : quantité × prix unitaire (le total correspond au prix de la version sur mesure).
        unit, kind, lkind = _cents(price), "offer", L.NAMED
        name = "Control Tower · Entreprise (sur mesure) · licence nominative"
    else:
        raise ApiError("VALIDATION_ERROR", "Choisissez une offre ou un nombre de licences.")

    payment = L.Payment.objects.create(tenant=tenant, created_by=by, kind=kind, offer_version=version, license_kind=lkind,
                                       quantity=qty, unit_amount=unit, amount=unit * qty, currency=currency,
                                       interval=interval, request=request_obj)
    base = base_url.rstrip("/")
    price_data = {"currency": currency.lower(), "unit_amount": unit, "product_data": {"name": name[:200]}}
    if interval:
        price_data["recurring"] = {"interval": interval}
    previous = L.Payment.objects.filter(tenant=tenant).exclude(stripe_customer="").values_list("stripe_customer", flat=True).first()
    params = {
        "mode": "subscription" if interval else "payment",
        "line_items": [{"price_data": price_data, "quantity": qty}],
        "success_url": f"{base}/?payment=success&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base}/?payment=cancelled",
        "client_reference_id": str(payment.pk),
        "metadata": {"payment_id": payment.pk, "tenant": tenant.slug},
        "locale": "fr",
        "allow_promotion_codes": True,
        "billing_address_collection": "required",
    }
    if previous:
        params["customer"] = previous
    else:
        email = by.email if by and not by.is_platform_admin and by.email else tenant.contact_email
        if email:
            params["customer_email"] = email
        if not interval:
            params["customer_creation"] = "always"
    if interval:
        params["subscription_data"] = {"metadata": {"payment_id": payment.pk, "tenant": tenant.slug}}
    else:
        params["invoice_creation"] = {"enabled": True}
    try:
        session = _stripe("POST", "/checkout/sessions", params)
    except ApiError as exc:
        payment.status, payment.error = L.Payment.FAILED, str(exc.detail)[:300]
        payment.save(update_fields=["status", "error"])
        raise
    payment.stripe_session, payment.checkout_url = session["id"], session.get("url", "")
    payment.save(update_fields=["stripe_session", "checkout_url"])
    audit.record(by, f"Paiement n° {payment.pk}", "Paiement Stripe initié", "",
                 f"{payment_row(payment)['label']} · {payment.amount / 100:.2f} {currency}", tenant=tenant)
    return payment


def confirm(session_id, user=None):
    """Retour de Stripe : vérifie la session auprès de Stripe puis applique le paiement (idempotent)."""
    payment = L.Payment.objects.select_related("tenant").filter(stripe_session=session_id).first()
    if payment is None:
        raise ApiError("NOT_FOUND", "Paiement introuvable.", status.HTTP_404_NOT_FOUND)
    if user is not None and not (user.is_platform_admin or user.tenant_id == payment.tenant_id
                                 or payment.created_by_id == user.pk):
        raise ApiError("NOT_FOUND", "Paiement introuvable.", status.HTTP_404_NOT_FOUND)
    if payment.status in (L.Payment.PENDING, L.Payment.PAID):
        session = _stripe("GET", f"/checkout/sessions/{session_id}")
        handle_session(session)
        payment.refresh_from_db()
    return payment


def handle_session(session):
    payment = L.Payment.objects.filter(stripe_session=session.get("id")).first()
    if payment is None:
        pid = (session.get("metadata") or {}).get("payment_id") or session.get("client_reference_id")
        payment = L.Payment.objects.filter(pk=pid).first() if str(pid or "").isdigit() else None
    if payment is None:
        return None
    if session.get("status") == "expired" and payment.status == L.Payment.PENDING:
        payment.status = L.Payment.EXPIRED
        payment.save(update_fields=["status"])
        return payment
    if session.get("status") != "complete" or session.get("payment_status") not in ("paid", "no_payment_required"):
        return payment
    with transaction.atomic():
        payment = L.Payment.objects.select_for_update().get(pk=payment.pk)
        if payment.status == L.Payment.PENDING:
            payment.status, payment.paid_at = L.Payment.PAID, timezone.now()
            payment.stripe_customer = session.get("customer") or ""
            payment.stripe_subscription = session.get("subscription") or ""
            payment.save(update_fields=["status", "paid_at", "stripe_customer", "stripe_subscription"])
    apply(payment)
    return payment


def _notify(tenant, title, body):
    from accounts.capabilities import has_capability
    users = [u for u in User.objects.filter(tenant=tenant, is_active=True) if u.is_app_admin or has_capability(u, "requests.view")]
    users += list(User.objects.filter(role_id=PLATFORM_ROLE, tenant__isnull=True, is_active=True))
    Notification.objects.bulk_create(Notification(user=u, event="validation_requested", title=title, body=body) for u in users)


def apply(payment):
    """Active l'offre ou ajoute les licences payées. Sans effet si déjà appliqué."""
    from . import services as lic
    with transaction.atomic():
        payment = L.Payment.objects.select_for_update().select_related("tenant", "offer_version__offer", "request", "created_by").get(pk=payment.pk)
        if payment.status != L.Payment.PAID:
            return payment
        by, tenant = payment.created_by, payment.tenant
        try:
            with transaction.atomic():
                req = payment.request
                if req is not None and req.status in (L.APPROVED, L.PARTIALLY_APPROVED):
                    lic.fulfil(by=by, req=req, comment=f"Payé en ligne (paiement n° {payment.pk}).")
                elif payment.kind == "offer":
                    lic.activate_offer(by=by, tenant=tenant, version=payment.offer_version, reason=f"Paiement Stripe n° {payment.pk}")
                else:
                    lic.allocate(by=by, tenant=tenant, kind=payment.license_kind, delta=payment.quantity,
                                 reason=f"Achat en ligne · paiement n° {payment.pk}")
        except (lic.LicenseError, ApiError) as exc:
            payment.error = (getattr(exc, "message", None) or str(getattr(exc, "detail", exc)))[:300]
            payment.save(update_fields=["error"])
            _notify(tenant, f"Paiement n° {payment.pk} reçu : action manuelle requise",
                    f"Le paiement est encaissé mais n'a pas pu être appliqué : {payment.error}")
            return payment
        payment.status, payment.applied_at, payment.error = L.Payment.APPLIED, timezone.now(), ""
        payment.save(update_fields=["status", "applied_at", "error"])
    label = payment_row(payment)["label"]
    audit.record(by, f"Paiement n° {payment.pk}", "Paiement reçu et appliqué", "Payé", label, tenant=tenant)
    _notify(tenant, f"Paiement reçu : {label}", f"{payment.amount / 100:.2f} {payment.currency} · {tenant.name}. "
                                                  "L'abonnement et les licences sont à jour.")
    return payment


# --------------------------------------------------------------------------- webhook
def verify_signature(payload: bytes, header: str, secret: str, tolerance=300):
    parts = {}
    for item in (header or "").split(","):
        k, _, v = item.partition("=")
        parts.setdefault(k.strip(), []).append(v.strip())
    try:
        ts = int(parts.get("t", ["0"])[0])
    except ValueError:
        return False
    if not ts or abs(time.time() - ts) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, sig) for sig in parts.get("v1", []))


def webhook(payload: bytes, signature: str):
    import json
    conf = config(with_secrets=True)
    if not conf["webhookSecret"] or not verify_signature(payload, signature, conf["webhookSecret"]):
        raise ApiError("FORBIDDEN_PERMISSION", "Signature Stripe invalide.", status.HTTP_400_BAD_REQUEST)
    event = json.loads(payload.decode("utf-8"))
    kind, obj = event.get("type", ""), (event.get("data") or {}).get("object") or {}
    if kind in ("checkout.session.completed", "checkout.session.async_payment_succeeded", "checkout.session.expired"):
        handle_session(obj)
    elif kind == "customer.subscription.deleted":
        for p in L.Payment.objects.filter(stripe_subscription=obj.get("id", "")).select_related("tenant"):
            p.status = L.Payment.CANCELLED
            p.save(update_fields=["status"])
            _notify(p.tenant, f"Abonnement Stripe résilié · {p.tenant.name}",
                    f"L'abonnement lié au paiement n° {p.pk} a été résilié côté Stripe. Vérifiez l'abonnement de l'entreprise.")
    elif kind == "invoice.payment_failed":
        sub_id = obj.get("subscription") or ""
        p = L.Payment.objects.filter(stripe_subscription=sub_id).select_related("tenant").first() if sub_id else None
        if p:
            _notify(p.tenant, f"Échec de prélèvement · {p.tenant.name}",
                    "Stripe n'a pas pu prélever le renouvellement de l'abonnement. Mettez à jour le moyen de paiement.")
    return kind
