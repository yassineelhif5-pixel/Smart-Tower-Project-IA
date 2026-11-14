"""Alertes de projet lancées par les utilisateurs et notifications aux membres du projet.

- Tout membre du projet (chef de projet, équipe, client, commercial…) peut lancer une alerte sur le projet
  ou sur une action précise : chaque membre la reçoit dans la cloche de l'application et par e-mail.
- Chaque dépôt de document notifie aussi tous les membres (les documents internes ne sont pas annoncés aux clients).
"""
import logging
import secrets
import threading

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit, notify
from configuration.models import AppSetting, Notification, NotificationChannel

from .models import Action, ProjectAccess

logger = logging.getLogger("notifications")

LEVELS = {"info": "Information", "warning": "Attention", "critical": "Critique"}
ICONS = {"info": "🔔", "warning": "⚠️", "critical": "🚨"}
SETTING_KEY = "project_user_alerts"
KEEP = 50


def members_of(project, internal_only=False):
    """Membres du projet : chef de projet, tech lead et utilisateurs affectés (actifs)."""
    User = get_user_model()
    ids = set(ProjectAccess.objects.filter(project=project).values_list("user_id", flat=True))
    ids |= {i for i in (project.pm_id, project.tl_id) if i}
    qs = User.objects.filter(pk__in=ids, is_active=True).select_related("role")
    users = list(qs)
    if internal_only:
        users = [u for u in users if u.role and u.role.internal]
    return users


def _send_mails(channel_id, recipients, subject, body):
    """Envoi des e-mails en arrière-plan pour ne pas ralentir l'écran de l'utilisateur."""
    try:
        channel = NotificationChannel.objects.select_related("tenant").get(pk=channel_id)
        for email in recipients:
            try:
                notify.send_email(channel, [email], subject, body)
            except notify.ChannelError:
                pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("Notification e-mail impossible : %s", type(exc).__name__)
    finally:
        close_old_connections()


def notify_members(project, by, title, body, internal_only=False, include_self=False, email=True, ref=None,
                   details=None, link=None):
    """Crée une notification (cloche) pour chaque membre et envoie l'e-mail. Renvoie (nb notifiés, nb e-mails).

    `ref` (« #ALxxxx », « #DOC:id ») permet à la cloche d'ouvrir le détail de l'alerte ou du document.
    L'auteur reçoit aussi la notification (déjà lue) quand include_self est vrai.
    """
    users = [u for u in members_of(project, internal_only) if include_self or u.pk != getattr(by, "pk", None)]
    full_title = f"[{project.code}] {title}"[:200]
    suffix = (f" · {ref}" if ref else "") + f" · {project.id}"
    now = timezone.now()
    Notification.objects.bulk_create([
        Notification(user=u, event="project_alert", title=full_title, body=f"{body[:1900]}{suffix}",
                     read_at=now if u.pk == getattr(by, "pk", None) else None) for u in users])
    others = [u for u in users if u.pk != getattr(by, "pk", None)]
    mails = [u.email for u in others if u.email] if email else []
    channel = NotificationChannel.objects.filter(tenant=project.tenant, kind="email", enabled=True).first() if mails else None
    if channel:
        lines = [full_title, "=" * min(len(full_title), 60), ""]
        lines += [f"{k} : {v}" for k, v in (details or {}).items() if v] or [body]
        lines += ["", f"Projet : {project.name} ({project.code})",
                  f"Par : {by.display_name if by else 'Smart Tower'} — {timezone.localtime(now).strftime('%d/%m/%Y %H:%M')}", ""]
        lines.append(f"Voir le détail : {link}" if link else
                     "Connectez-vous à Smart Tower : le détail est dans le centre de notifications (cloche en haut de l'écran).")
        threading.Thread(target=_send_mails, args=(channel.pk, mails, full_title, "\n".join(lines)), daemon=True).start()
    return len(others), len(mails) if channel else 0


def app_link(request, project, extra=""):
    """Lien vers le projet dans l'application (origine du navigateur de l'utilisateur)."""
    origin = (request.headers.get("Origin") or "").rstrip("/") if request else ""
    if not origin.startswith(("http://", "https://")):
        return None
    return f"{origin}/#projets/{project.id}{extra}"


def notify_new_document(project, by, doc, type_label, request=None):
    body = f"Nouveau document « {doc.name} » ({type_label}, v{doc.version}) déposé par {by.display_name}"
    details = {"Document": doc.name, "Type": type_label, "Version": f"v{doc.version}",
               "Description": doc.description, "Déposé par": by.display_name}
    return notify_members(project, by, f"📄 Nouveau document : {doc.name}", body, internal_only=not doc.client_visible,
                          ref=f"#DOC:{doc.id}", details=details, link=app_link(request, project))


def alert_details(tenant):
    """Index des alertes lancées (id → alerte) pour afficher leur détail dans la cloche."""
    row = AppSetting.objects.filter(tenant=tenant, key=SETTING_KEY).first()
    data = row.value if row and isinstance(row.value, dict) else {}
    return {a["id"]: {**a, "project": pid} for pid, items in data.items() for a in items}


def _store(project):
    row = AppSetting.objects.filter(tenant=project.tenant, key=SETTING_KEY).first()
    data = row.value if row and isinstance(row.value, dict) else {}
    return row, data


def launch_alert(project, by, title, message, level="warning", action=None, client_visible=True, email=True, link=None,
                 by_label=None):
    """Lance une alerte de projet (utilisateur ou Chef de projet IA) : cloche + e-mail pour tous les membres, historique."""
    level = level if level in LEVELS else "warning"
    author = by_label or (by.display_name if by else "Chef de projet IA")
    about = f"Action {action.pk} « {action.title} »" if action else "Projet"
    body = f"{LEVELS[level]} · {about}" + (f" — {message}" if message else "") + f" · alerte lancée par {author}"
    alert_id = f"AL{secrets.token_hex(4).upper()}"
    details = {"Alerte": title, "Niveau": LEVELS[level], "Concerne": about, "Message": message, "Lancée par": author}
    count, mailed = notify_members(project, by, f"{ICONS[level]} Alerte : {title}", body, internal_only=not client_visible,
                                   email=email, include_self=True, ref=f"#{alert_id}", details=details, link=link)
    alert = {"id": alert_id, "title": title, "message": message, "level": level, "levelLabel": LEVELS[level],
             "action": action.pk if action else None, "actionTitle": action.title if action else None, "by": author,
             "byId": by.pk if by else None, "at": timezone.now().isoformat(), "clientVisible": client_visible,
             "closed": False, "notified": count, "mailed": mailed}
    row, data = _store(project)
    data[project.id] = ([alert] + data.get(project.id, []))[:KEEP]
    if row:
        row.value = data
        row.save(update_fields=["value", "updated_at"])
    else:
        AppSetting.objects.create(tenant=project.tenant, key=SETTING_KEY, value=data)
    audit.record(by, f"Projet {project.code}", "Alerte lancée", "", f"{title} ({LEVELS[level]}, {about}) — {author}",
                 tenant=project.tenant)
    return alert


class ProjectUserAlertsView(APIView):
    """GET : alertes lancées sur le projet. POST : lancer une alerte (tout membre du projet). PATCH : clôturer une alerte."""

    def _project(self, request, pk):
        from .workspace import _project
        return _project(request.user, pk)

    def get(self, request, pk):
        project = self._project(request, pk)
        _, data = _store(project)
        items = data.get(project.id, [])
        internal = bool(request.user.role and request.user.role.internal)
        if not internal:
            items = [a for a in items if a.get("clientVisible", True)]
        from .workspace import _rights
        r = _rights(request.user, project)
        boss = r["isPm"] or r["isTl"] or request.user.is_app_admin
        items = [{**a, "canClose": boss or a.get("byId") == request.user.pk} for a in items]
        return Response({"levels": [{"code": k, "label": v} for k, v in LEVELS.items()], "internal": internal, "alerts": items})

    def post(self, request, pk):
        project = self._project(request, pk)
        title = str(request.data.get("title") or "").strip()[:150]
        message = str(request.data.get("message") or "").strip()[:2000]
        level = request.data.get("level") or "warning"
        if not title:
            raise ApiError("VALIDATION_ERROR", "Donnez un titre à l'alerte.")
        if level not in LEVELS:
            raise ApiError("VALIDATION_ERROR", "Niveau d'alerte inconnu.")
        action = None
        action_id = request.data.get("action")
        if action_id:
            action = Action.objects.filter(project=project, pk=action_id).first()
            if action is None:
                raise ApiError("VALIDATION_ERROR", "Action introuvable sur ce projet.")
        internal = bool(request.user.role and request.user.role.internal)
        client_visible = True if not internal else str(request.data.get("clientVisible", "true")).lower() in ("1", "true", "on")
        alert = launch_alert(project, request.user, title, message, level, action=action, client_visible=client_visible,
                             email=request.data.get("email", True) is not False, link=app_link(request, project))
        return Response(alert, status=status.HTTP_201_CREATED)

    def patch(self, request, pk):
        project = self._project(request, pk)
        from .workspace import _rights
        row, data = _store(project)
        items = data.get(project.id, [])
        alert = next((a for a in items if a["id"] == request.data.get("id")), None)
        if alert is None:
            raise ApiError("NOT_FOUND", "Alerte introuvable.", status.HTTP_404_NOT_FOUND)
        r = _rights(request.user, project)
        if not (alert.get("byId") == request.user.pk or r["isPm"] or r["isTl"] or request.user.is_app_admin):
            raise ApiError("FORBIDDEN_PERMISSION", "Seul l'auteur, le chef de projet ou l'administrateur peut clôturer l'alerte.",
                           status.HTTP_403_FORBIDDEN)
        alert["closed"] = bool(request.data.get("closed", True))
        alert["closedBy"] = request.user.display_name
        row.value = data
        row.save(update_fields=["value", "updated_at"])
        return Response(alert)
