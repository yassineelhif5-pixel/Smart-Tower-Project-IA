"""OpenID Connect Authorization Code + PKCE for mapped tenant email domains."""
from __future__ import annotations

import ipaddress
import secrets
import socket
from datetime import datetime, timedelta, timezone as datetime_timezone
from urllib.parse import urlparse

import requests
from authlib.integrations.requests_client import OAuth2Session
from authlib.oidc.core import CodeIDToken
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone
from joserfc import jwt
from joserfc.jwk import KeySet

from configuration import audit
from configuration.models import ServiceSecret
from tenants.domain_utils import email_domain
from tenants.models import TenantDomain

from .models import SSOAccessRequest, SSOConnector, SSOIdentity

User = get_user_model()
SESSION_KEY = "pct_sso_oidc"
SCOPE = "openid email profile"
ALGORITHMS = ["RS256"]


class SSOError(Exception):
    pass


def callback_uri(request):
    base = settings.PUBLIC_BASE_URL or request.build_absolute_uri("/").rstrip("/")
    return f"{base.rstrip('/')}/api/v1/auth/sso/callback"


def _public_https_url(value):
    parsed = urlparse(str(value or ""))
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise SSOError("Le fournisseur SSO doit utiliser une adresse HTTPS publique.")
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise SSOError("L’adresse du fournisseur SSO est invalide.") from exc
    if parsed.query or parsed.port not in (None, 443):
        raise SSOError("Le fournisseur SSO doit utiliser le port HTTPS standard.")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".test")):
        raise SSOError("L’adresse du fournisseur SSO n’est pas autorisée.")
    try:
        ip = ipaddress.ip_address(host)
        addresses = [ip]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]
        except (OSError, ValueError) as exc:
            raise SSOError("Le fournisseur SSO est injoignable.") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise SSOError("L’adresse du fournisseur SSO n’est pas publique.")
    return parsed.geturl()


def _get_json(url):
    _public_https_url(url)
    try:
        response = requests.get(url, timeout=(3, 8), allow_redirects=False, headers={"Accept": "application/json"})
        if response.status_code != 200 or len(response.content) > 524_288:
            raise SSOError("Le fournisseur SSO n’a pas renvoyé une configuration valide.")
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise SSOError("Impossible de joindre le fournisseur SSO.") from exc
    if not isinstance(data, dict):
        raise SSOError("Le fournisseur SSO n’a pas renvoyé une configuration valide.")
    return data


def discovery(issuer):
    issuer = str(issuer or "").strip().rstrip("/")
    _public_https_url(issuer)
    metadata = _get_json(f"{issuer}/.well-known/openid-configuration")
    if metadata.get("issuer", "").rstrip("/") != issuer:
        raise SSOError("L’émetteur annoncé ne correspond pas à l’émetteur configuré.")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not metadata.get(key):
            raise SSOError("Le fournisseur SSO ne publie pas les points de terminaison requis.")
        _public_https_url(metadata[key])
    return metadata


def _client(connector, secret, redirect_uri, state=None):
    client = OAuth2Session(
        connector.client_id,
        secret,
        scope=SCOPE,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge_method="S256",
        default_timeout=8,
    )
    client.max_redirects = 0
    return client


def begin(request, email, provider=""):
    _, domain = email_domain(email)
    mapping = TenantDomain.objects.select_related("tenant").filter(domain=domain, enabled=True).first()
    if not mapping or mapping.tenant.status != "active":
        raise SSOError("Aucune connexion SSO active n’est associée à cette adresse.")
    connector = SSOConnector.objects.select_related("tenant", "default_role").filter(tenant=mapping.tenant, enabled=True).first()
    if not connector:
        raise SSOError("La connexion SSO de cette entreprise n’est pas activée.")
    secret = ServiceSecret.value_of(mapping.tenant, "sso_client_secret")
    if not secret or not connector.client_id:
        raise SSOError("La connexion SSO de cette entreprise n’est pas complète.")
    metadata = discovery(connector.issuer)
    issuer_host = (urlparse(connector.issuer).hostname or "").lower()
    if provider == "microsoft" and issuer_host not in {"login.microsoftonline.com", "sts.windows.net"}:
        raise SSOError("Microsoft n’est pas le fournisseur SSO configuré pour ce domaine.")
    if provider == "google" and issuer_host not in {"accounts.google.com"}:
        raise SSOError("Google n’est pas le fournisseur SSO configuré pour ce domaine.")
    if provider not in {"", "microsoft", "google"}:
        raise SSOError("Fournisseur SSO inconnu.")
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    redirect = callback_uri(request)
    client = _client(connector, secret, redirect, state)
    authorization_url, _ = client.create_authorization_url(
        metadata["authorization_endpoint"], state=state, code_verifier=verifier,
        nonce=nonce, redirect_uri=redirect, scope=SCOPE, response_type="code",
    )
    request.session[SESSION_KEY] = {
        "state": state, "nonce": nonce, "verifier": verifier,
        "domain": domain, "tenant": mapping.tenant_id, "connector": connector.pk,
        "issuer": connector.issuer.rstrip("/"), "at": timezone.now().isoformat(),
    }
    request.session.save()
    return authorization_url


def _identity_claims(token_response, metadata, connector, secret, nonce, redirect_uri):
    id_token = token_response.get("id_token")
    if not id_token:
        raise SSOError("Le fournisseur SSO n’a pas renvoyé de jeton d’identité.")
    keyset_data = _get_json(metadata["jwks_uri"])
    try:
        keyset = KeySet.import_key_set(keyset_data)
        parsed = jwt.decode(id_token, keyset, algorithms=ALGORITHMS)
        identity = CodeIDToken(
            parsed.claims, parsed.header,
            options={
                "iss": {"essential": True, "value": connector.issuer.rstrip("/")},
                "aud": {"essential": True, "value": connector.client_id},
            },
            params={"nonce": nonce, "client_id": connector.client_id, "access_token": token_response.get("access_token")},
        )
        identity.validate(leeway=60)
    except Exception as exc:
        raise SSOError("Le jeton SSO n’est pas valide pour cette application.") from exc
    return dict(identity)


def _username(email, tenant):
    local = email.split("@", 1)[0]
    stem = "".join(ch if ch.isalnum() or ch in "_.+-" else "_" for ch in local)[:60].strip("._+-") or "sso-user"
    base = f"{stem}-{tenant.slug[:35]}"[:149]
    candidate, suffix = base, 1
    while User.objects.filter(username__iexact=candidate).exists():
        suffix += 1
        tail = f"-{suffix}"
        candidate = base[:150 - len(tail)] + tail
    return candidate


@transaction.atomic
def get_or_provision_user(*, connector, tenant, claims, domain):
    email = str(claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    try:
        _, claimed_domain = email_domain(email)
    except ValueError as exc:
        raise SSOError("Le fournisseur SSO n’a pas fourni une adresse e-mail valide.") from exc
    if claimed_domain != domain:
        raise SSOError("L’adresse du compte ne correspond pas au domaine attribué par le Pilote.")
    if claims.get("email_verified") is False:
        raise SSOError("Le fournisseur SSO indique que l’adresse e-mail n’est pas vérifiée.")
    subject, issuer = str(claims.get("sub") or ""), connector.issuer.rstrip("/")
    if not subject or len(subject) > 255:
        raise SSOError("Le fournisseur SSO n’a pas fourni d’identifiant stable.")
    identity = SSOIdentity.objects.select_related("user").filter(issuer=issuer, subject=subject).first()
    if identity:
        if identity.tenant_id != tenant.pk or identity.user.tenant_id != tenant.pk:
            raise SSOError("Cette identité SSO est déjà rattachée à une autre entreprise.")
        user = identity.user
        if not user.is_active:
            raise SSOError("Ce compte est désactivé. Contactez l’administrateur de votre entreprise.")
        identity.email = email
        identity.save(update_fields=["email"])
        return user

    user = User.objects.filter(email__iexact=email).first()
    if user is not None:
        if user.tenant_id != tenant.pk or not user.is_active:
            raise SSOError("Cette adresse est déjà rattachée à un compte différent.")
        try:
            with transaction.atomic():
                SSOIdentity.objects.create(tenant=tenant, user=user, issuer=issuer, subject=subject, email=email)
        except IntegrityError as exc:
            existing = SSOIdentity.objects.select_related("user").filter(issuer=issuer, subject=subject).first()
            if not existing or existing.user_id != user.pk:
                raise SSOError("Cette identité SSO est déjà utilisée.") from exc
        return user

    request, created = SSOAccessRequest.objects.get_or_create(
        issuer=issuer, subject=subject,
        defaults={"tenant": tenant, "email": email,
                  "first_name": str(claims.get("given_name", ""))[:150],
                  "last_name": str(claims.get("family_name", ""))[:150]},
    )
    if request.tenant_id != tenant.pk or request.email.lower() != email:
        raise SSOError("Cette identité SSO est déjà associée à une autre demande.")
    if created:
        audit.record(None, f"Demande SSO {email}", "Nouvelle demande d’accès", "", domain, tenant=tenant)
    return None


def finish(request, code, state):
    pending = request.session.pop(SESSION_KEY, None)
    if not pending or not state or not secrets.compare_digest(str(pending.get("state", "")), str(state)):
        raise SSOError("La demande de connexion a expiré ou est invalide. Recommencez.")
    try:
        started = datetime.fromisoformat(pending["at"])
        if started.tzinfo is None:
            started = started.replace(tzinfo=datetime_timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise SSOError("La demande de connexion a expiré. Recommencez.") from exc
    if timezone.now() - started > timedelta(minutes=10):
        raise SSOError("La demande de connexion a expiré. Recommencez.")
    mapping = TenantDomain.objects.select_related("tenant").filter(
        domain=pending["domain"], enabled=True, tenant_id=pending["tenant"], tenant__status="active"
    ).first()
    connector = SSOConnector.objects.select_related("default_role", "tenant").filter(
        pk=pending["connector"], tenant_id=pending["tenant"], enabled=True
    ).first()
    if not mapping or not connector or connector.issuer.rstrip("/") != pending["issuer"]:
        raise SSOError("L’association du domaine ou la configuration SSO a changé. Recommencez.")
    if request.query_params.get("error"):
        raise SSOError("La connexion a été refusée par le fournisseur SSO.")
    if not code:
        raise SSOError("Le fournisseur SSO n’a pas renvoyé de code de connexion.")
    secret = ServiceSecret.value_of(mapping.tenant, "sso_client_secret")
    if not secret:
        raise SSOError("La configuration SSO est incomplète.")
    metadata = discovery(connector.issuer)
    redirect = callback_uri(request)
    client = _client(connector, secret, redirect, pending["state"])
    client.token_endpoint = metadata["token_endpoint"]
    try:
        token_response = client.fetch_token(
            metadata["token_endpoint"], authorization_response=request.build_absolute_uri(),
            code_verifier=pending["verifier"], allow_redirects=False, timeout=8,
        )
    except Exception as exc:
        raise SSOError("L’échange avec le fournisseur SSO a échoué.") from exc
    claims = _identity_claims(token_response, metadata, connector, secret, pending["nonce"], redirect)
    return get_or_provision_user(connector=connector, tenant=mapping.tenant, claims=claims, domain=mapping.domain)
