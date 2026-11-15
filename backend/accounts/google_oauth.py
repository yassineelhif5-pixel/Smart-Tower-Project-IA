"""« Continuer avec Google » au niveau de la plateforme (client OAuth configuré par le Pilote).

Indépendant du SSO d'entreprise : n'importe quelle adresse Google vérifiée peut se connecter. Un compte existant
avec la même adresse est relié ; sinon un compte libre est créé et suit le parcours d'accueil.
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from configuration import audit

from .models import SignupProfile
from .sso import SSOError, _client, _identity_claims, discovery

User = get_user_model()
ISSUER = "https://accounts.google.com"
SETTING_KEY = "google_oauth"
SESSION_KEY = "pct_google_oauth"


def _row():
    from configuration.models import PlatformSetting
    return PlatformSetting.objects.filter(key=SETTING_KEY).first()


def config(with_secret=False):
    """Réglage du Pilote (prioritaire) sinon variables GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET."""
    from configuration import crypto
    row = _row()
    v = dict(row.value or {}) if row else {}
    client_id = (v.get("client_id") or "").strip()
    secret = ""
    source = "pilot" if client_id else ""
    if client_id and v.get("client_secret"):
        try:
            secret = crypto.decrypt(v["client_secret"])
        except Exception:  # noqa: BLE001
            secret = ""
    if not client_id:
        client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
        secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
        source = "env" if client_id else ""
    enabled = bool(client_id and secret) and v.get("enabled", True) is not False
    out = {"clientId": client_id, "hasSecret": bool(secret), "secretHint": v.get("hint", "") if source == "pilot" else "",
           "enabled": enabled, "source": source,
           "updatedAt": row.updated_at if row else None,
           "updatedBy": row.updated_by.display_name if row and row.updated_by_id else ""}
    if with_secret:
        out["secret"] = secret
    return out


def callback_uri(request):
    base = settings.PUBLIC_BASE_URL or request.build_absolute_uri("/").rstrip("/")
    return f"{base.rstrip('/')}/api/v1/auth/google/callback"


def _connector(conf):
    return SimpleNamespace(client_id=conf["clientId"], issuer=ISSUER)


def begin(request):
    conf = config(with_secret=True)
    if not conf["enabled"]:
        raise SSOError("La connexion Google n'est pas encore configurée par le Pilote.")
    metadata = discovery(ISSUER)
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    redirect = callback_uri(request)
    client = _client(_connector(conf), conf["secret"], redirect, state)
    url, _ = client.create_authorization_url(metadata["authorization_endpoint"], state=state, code_verifier=verifier,
                                             nonce=nonce, redirect_uri=redirect, scope="openid email profile",
                                             response_type="code", prompt="select_account")
    request.session[SESSION_KEY] = {"state": state, "nonce": nonce, "verifier": verifier, "at": timezone.now().isoformat()}
    request.session.save()
    return url


def finish(request, code, state):
    pending = request.session.pop(SESSION_KEY, None)
    if not pending or not state or not secrets.compare_digest(str(pending.get("state", "")), str(state)):
        raise SSOError("La demande de connexion a expiré. Recommencez.")
    try:
        started = datetime.fromisoformat(pending["at"])
        if started.tzinfo is None:
            started = started.replace(tzinfo=dt_timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise SSOError("La demande de connexion a expiré.") from exc
    if timezone.now() - started > timedelta(minutes=10):
        raise SSOError("La demande de connexion a expiré. Recommencez.")
    if request.query_params.get("error") or not code:
        raise SSOError("La connexion a été annulée.")
    conf = config(with_secret=True)
    if not conf["enabled"]:
        raise SSOError("La connexion Google n'est pas configurée.")
    metadata = discovery(ISSUER)
    redirect = callback_uri(request)
    client = _client(_connector(conf), conf["secret"], redirect, pending["state"])
    client.token_endpoint = metadata["token_endpoint"]
    try:
        token = client.fetch_token(metadata["token_endpoint"], authorization_response=request.build_absolute_uri(),
                                   code_verifier=pending["verifier"], allow_redirects=False, timeout=8)
    except Exception as exc:
        raise SSOError("L'échange avec Google a échoué.") from exc
    claims = _identity_claims(token, metadata, _connector(conf), conf["secret"], pending["nonce"], redirect)
    return get_or_create_user(claims)


@transaction.atomic
def get_or_create_user(claims):
    from .signup import unique_username
    email = str(claims.get("email") or "").strip().lower()
    sub = str(claims.get("sub") or "")
    if not email or not sub or len(sub) > 255:
        raise SSOError("Google n'a pas fourni d'adresse e-mail.")
    if claims.get("email_verified") is not True:
        raise SSOError("Votre adresse Google n'est pas vérifiée.")
    profile = SignupProfile.objects.select_related("user").filter(google_sub=sub).first()
    if profile:
        user = profile.user
    else:
        user = User.objects.filter(email__iexact=email).order_by("id").first()
        if user is None:
            user = User(username=unique_username(email), email=email, is_active=True, auth_mode="both",
                        first_name=str(claims.get("given_name") or "")[:150], last_name=str(claims.get("family_name") or "")[:150])
            user.set_unusable_password()
            user.save()
            SignupProfile.objects.create(user=user, source="google", email_verified=True, google_sub=sub)
            audit.record(None, f"Utilisateur {user.username}", "Inscription avec Google", tenant=None)
        else:
            p, _ = SignupProfile.objects.get_or_create(user=user, defaults={"source": "google", "email_verified": True,
                                                                            "profile_done": bool(user.tenant_id)})
            if p.google_sub and p.google_sub != sub:
                raise SSOError("Cette adresse est déjà reliée à un autre compte Google.")
            p.google_sub, p.email_verified = sub, True
            p.save(update_fields=["google_sub", "email_verified"])
    if not user.is_active:
        raise SSOError("Ce compte est désactivé.")
    return user
