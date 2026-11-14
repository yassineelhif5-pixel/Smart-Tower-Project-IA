"""Structure de l'équipe d'un projet : organigramme humain + assistants IA, charge en cours, absences et remplaçants.

- Accessible à toute personne qui voit le projet (interne ou client).
- Charge : part des actions en cours du projet (non terminées) portée par chaque personne, plus sa charge tous projets.
- Absences : déclarées ici (réglage « team_absences » de l'entreprise) ou issues des délégations d'absence existantes
  (validation des temps) ; la personne apparaît « Absente · remplacée par … ».
- Photos de profil : chacun dépose la sienne (image redimensionnée par le navigateur, stockée en base).
"""
import base64
import binascii
import secrets
from datetime import date

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserPhoto
from config.errors import ApiError
from configuration import audit
from configuration.models import AppSetting, Notification

from .models import Action, Project, ProjectAccess, TimeApprovalDelegation
from .workspace import _project, _rights

KEY = "team_absences"
OPEN = ("todo", "planned", "doing", "review", "blocked")
MAX_PHOTO = 400_000


# --------------------------------------------------------------------------- absences
def _absences_store(tenant):
    row = AppSetting.objects.filter(tenant=tenant, key=KEY).first()
    data = row.value if row and isinstance(row.value, list) else []
    return row, data


def _save_absences(tenant, row, data):
    if row:
        row.value = data
        row.save(update_fields=["value", "updated_at"])
    else:
        AppSetting.objects.create(tenant=tenant, key=KEY, value=data)


def current_absences(tenant, day=None):
    """{user_id: {from, to, reason, replacement, source}} des absences en cours (ou à venir sous 7 jours)."""
    day = day or timezone.localdate()
    out = {}
    _, data = _absences_store(tenant)
    for a in data:
        start, end = parse_date(a.get("start") or ""), parse_date(a.get("end") or "")
        if not start or not end or end < day:
            continue
        upcoming = start > day
        if upcoming and (start - day).days > 7:
            continue
        prev = out.get(a["user"])
        if prev and not prev["upcoming"]:
            continue
        out[a["user"]] = {"id": a["id"], "from": a["start"], "to": a["end"], "reason": a.get("reason", ""),
                          "replacement": a.get("replacement"), "upcoming": upcoming, "source": "declared"}
    for d in TimeApprovalDelegation.objects.filter(tenant=tenant, start_date__lte=day, end_date__gte=day):
        out.setdefault(d.delegator_id, {"id": f"deleg-{d.pk}", "from": d.start_date.isoformat(), "to": d.end_date.isoformat(),
                                        "reason": d.reason or "Absence", "replacement": d.delegate_id, "upcoming": False,
                                        "source": "delegation"})
    return out


# --------------------------------------------------------------------------- photos
def _photo_versions(ids):
    return {p["user_id"]: int(p["updated_at"].timestamp()) for p in UserPhoto.objects.filter(user_id__in=ids).values("user_id", "updated_at")}


class UserPhotoView(APIView):
    """GET /users/<id>/photo : photo d'un utilisateur de la même entreprise."""

    def get(self, request, uid):
        User = get_user_model()
        u = get_object_or_404(User, pk=uid)
        me = request.user
        same = u.tenant_id == me.tenant_id or u.memberships.filter(tenant_id=me.tenant_id).exists()
        if not same and not me.is_platform_admin:
            raise ApiError("NOT_FOUND", "Photo introuvable.", status.HTTP_404_NOT_FOUND)
        p = UserPhoto.objects.filter(user=u).first()
        if p is None:
            raise ApiError("NOT_FOUND", "Pas de photo.", status.HTTP_404_NOT_FOUND)
        resp = HttpResponse(bytes(p.content), content_type=p.mime)
        resp["Cache-Control"] = "private, max-age=86400"
        resp["X-Content-Type-Options"] = "nosniff"
        return resp


class MyPhotoView(APIView):
    """PUT {image: dataURL} : dépose / remplace sa photo ; DELETE : la retire."""

    def put(self, request):
        raw = str(request.data.get("image") or "")
        if not raw.startswith("data:image/") or ";base64," not in raw:
            raise ApiError("VALIDATION_ERROR", "Image invalide.")
        head, b64 = raw.split(";base64,", 1)
        mime = head[5:]
        if mime not in ("image/jpeg", "image/png", "image/webp"):
            raise ApiError("VALIDATION_ERROR", "Format accepté : JPEG, PNG ou WebP.")
        try:
            content = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError):
            raise ApiError("VALIDATION_ERROR", "Image illisible.")
        if len(content) > MAX_PHOTO:
            raise ApiError("VALIDATION_ERROR", "Image trop lourde (400 Ko maximum après redimensionnement).")
        UserPhoto.objects.update_or_create(user=request.user, defaults={"content": content, "mime": mime})
        audit.record(request.user, f"Utilisateur {request.user.username}", "Photo de profil modifiée", "", "", tenant=request.user.tenant)
        return Response({"ok": True, "version": int(timezone.now().timestamp())})

    def delete(self, request):
        UserPhoto.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- structure
def _person(u, photos):
    role = u.role
    return {"id": u.pk, "name": u.display_name, "title": u.title or (role.label if role else ""), "role": role.label if role else "",
            "roleCode": u.role_id or "", "internal": bool(role and role.internal), "team": u.team or "",
            "photo": photos.get(u.pk)}


def can_manage_absences(user, project=None):
    if user.is_app_admin:
        return True
    if project is not None:
        r = _rights(user, project)
        return r["isPm"] or r["isTl"]
    return Project.objects.filter(Q(pm=user) | Q(tl=user), tenant_id=user.tenant_id).exists()


class TeamStructureView(APIView):
    def get(self, request, pk):
        project = _project(request.user, pk)
        User = get_user_model()
        today = timezone.localdate()
        viewer_internal = bool(request.user.role and request.user.role.internal)

        ids = set(ProjectAccess.objects.filter(project=project).values_list("user_id", flat=True))
        ids |= {i for i in (project.pm_id, project.tl_id) if i}
        users = {u.pk: u for u in User.objects.filter(pk__in=ids, is_active=True).select_related("role")}
        # Interlocuteurs côté client : utilisateurs externes rattachés au client du projet.
        if project.client_id:
            for u in User.objects.filter(tenant=project.tenant, client_id=project.client_id, is_active=True).select_related("role"):
                if not (u.role and u.role.internal):
                    users.setdefault(u.pk, u)

        acts = Action.objects.filter(project=project)
        total_open = acts.filter(status__in=OPEN).count()
        per = {r["owner_id"]: r for r in acts.filter(status__in=OPEN, owner__isnull=False).values("owner_id").annotate(
            open=Count("id"), doing=Count("id", filter=Q(status="doing")), blocked=Count("id", filter=Q(status="blocked")),
            late=Count("id", filter=Q(due__lt=today)))}
        done = {r["owner_id"]: r["n"] for r in acts.filter(status="done", owner__isnull=False).values("owner_id").annotate(n=Count("id"))}
        everywhere = {r["owner_id"]: r for r in Action.objects.filter(
            tenant=project.tenant, status__in=OPEN, owner_id__in=list(users), project__status="active").values("owner_id").annotate(
            n=Count("id"), projects=Count("project", distinct=True))}
        absences = current_absences(project.tenant, today)
        # Remplaçants qui ne sont pas membres : affichés quand même (nom + photo).
        repl_ids = {a["replacement"] for uid, a in absences.items() if uid in users and a.get("replacement")}
        extra = {u.pk: u for u in User.objects.filter(pk__in=repl_ids - set(users)).select_related("role")}
        photos = _photo_versions(list(users) + list(extra))

        def load(uid):
            r = per.get(uid) or {}
            e = everywhere.get(uid) or {}
            n = r.get("open", 0)
            return {"open": n, "doing": r.get("doing", 0), "blocked": r.get("blocked", 0), "late": r.get("late", 0),
                    "done": done.get(uid, 0), "share": round(n * 100 / total_open) if total_open else 0,
                    "allOpen": e.get("n", 0), "allProjects": e.get("projects", 0)}

        people = []
        for uid, u in users.items():
            row = _person(u, photos)
            row["position"] = "pm" if uid == project.pm_id else "tl" if uid == project.tl_id else ("member" if row["internal"] else "client")
            row["side"] = "internal" if row["internal"] else "client"
            row["load"] = load(uid)
            if viewer_internal:
                row["email"] = u.email
            a = absences.get(uid)
            if a:
                rep = users.get(a.get("replacement")) or extra.get(a.get("replacement"))
                row["absence"] = {**a, "replacement": _person(rep, photos) if rep else None}
            row["replacing"] = [users[x].display_name for x, a in absences.items()
                                if a.get("replacement") == uid and x in users and not a.get("upcoming")]
            people.append(row)
        order = {"pm": 0, "tl": 1, "member": 2, "client": 3}
        people.sort(key=lambda r: (order[r["position"]], -r["load"]["open"], r["name"]))

        # Équipe IA : assistants actifs sur le projet, avec leurs propositions en attente.
        ai = []
        try:
            from .ai_orchestrator import ROSTER, team_conf
            from .assistant_review import _store
            conf = team_conf(project)
            _, data = _store(project)
            pending = (data.get(project.id) or {}).get("pending") or []
            tot = len(pending)
            for code, a in conf["assistants"].items():
                if not a["enabled"]:
                    continue
                n = sum(1 for p in pending if p.get("assistant") == code)
                ai.append({"code": code, **{k: ROSTER[code][k] for k in ("name", "role", "avatar", "color", "mission")},
                           "mode": a["mode"], "modeLabel": "Automatique" if a["mode"] == "auto" else "En binôme (validation)",
                           "pending": n, "share": round(n * 100 / tot) if tot else 0})
            licensed = conf["licensed"]
        except Exception:  # module IA indisponible : l'organigramme humain reste affiché
            licensed = False

        unassigned = acts.filter(status__in=OPEN, owner__isnull=True).count()
        return Response({
            "project": {"id": project.id, "code": project.code, "name": project.name,
                        "client": {"code": project.client.code, "name": project.client.name} if project.client_id else None,
                        "status": project.status},
            "totals": {"open": total_open, "unassigned": unassigned, "late": acts.filter(status__in=OPEN, due__lt=today).count(),
                       "done": acts.filter(status="done").count(), "people": len(people),
                       "absent": sum(1 for p in people if p.get("absence") and not p["absence"]["upcoming"])},
            "people": people, "ai": ai, "aiLicensed": licensed,
            "me": request.user.pk, "canManageAbsences": can_manage_absences(request.user, project),
            "candidates": [_person(u, photos) for u in sorted(users.values(), key=lambda x: x.display_name) if u.role and u.role.internal],
        })


class TeamAbsencesView(APIView):
    """POST : déclarer une absence (soi-même, ou chef de projet / tech lead / admin) ; DELETE <id> : la retirer."""

    def post(self, request):
        user = request.user
        User = get_user_model()
        target = get_object_or_404(User, pk=request.data.get("user"), tenant_id=user.tenant_id)
        project = None
        if request.data.get("project"):
            project = _project(user, request.data["project"])
        if target.pk != user.pk and not can_manage_absences(user, project):
            raise ApiError("FORBIDDEN_PERMISSION", "Seuls la personne elle-même, le chef de projet, le tech lead ou "
                                                   "l'administrateur peuvent déclarer une absence.", status.HTTP_403_FORBIDDEN)
        start, end = parse_date(str(request.data.get("start") or "")), parse_date(str(request.data.get("end") or ""))
        if not start or not end or end < start:
            raise ApiError("VALIDATION_ERROR", "Indiquez une période valide (début ≤ fin).")
        rep = None
        if request.data.get("replacement"):
            rep = get_object_or_404(User, pk=request.data["replacement"], tenant_id=user.tenant_id, is_active=True)
            if rep.pk == target.pk:
                raise ApiError("VALIDATION_ERROR", "Le remplaçant doit être une autre personne.")
        row, data = _absences_store(user.tenant)
        today = timezone.localdate()
        data = [a for a in data if (parse_date(a.get("end") or "") or today) >= date(today.year - 1, 1, 1)]  # purge des anciennes
        entry = {"id": f"AB{secrets.token_hex(4).upper()}", "user": target.pk, "start": start.isoformat(), "end": end.isoformat(),
                 "replacement": rep.pk if rep else None, "reason": str(request.data.get("reason") or "")[:200],
                 "by": user.display_name, "byId": user.pk, "at": timezone.now().isoformat()}
        data.append(entry)
        _save_absences(user.tenant, row, data)
        audit.record(user, f"Utilisateur {target.username}", "Absence déclarée", "",
                     f"{start:%d/%m/%Y} → {end:%d/%m/%Y}" + (f", remplacé par {rep.display_name}" if rep else ""), tenant=user.tenant)
        if rep and rep.pk != user.pk:
            Notification.objects.create(
                user=rep, event="project_alert", title=f"🔁 Vous remplacez {target.display_name}"[:200],
                body=f"{target.display_name} est absent(e) du {start:%d/%m/%Y} au {end:%d/%m/%Y}"
                     + (f" ({entry['reason']})" if entry["reason"] else "") + f". Déclaré par {user.display_name}."
                     + (f" · {project.id}" if project else ""))
        if target.pk != user.pk:
            Notification.objects.create(
                user=target, event="project_alert", title="🌴 Absence enregistrée",
                body=f"Absence du {start:%d/%m/%Y} au {end:%d/%m/%Y}" + (f", remplacé(e) par {rep.display_name}" if rep else "")
                     + f". Déclarée par {user.display_name}." + (f" · {project.id}" if project else ""))
        return Response(entry, status=status.HTTP_201_CREATED)

    def delete(self, request, aid):
        user = request.user
        row, data = _absences_store(user.tenant)
        a = next((x for x in data if x.get("id") == aid), None)
        if a is None:
            raise ApiError("NOT_FOUND", "Absence introuvable.", status.HTTP_404_NOT_FOUND)
        if a["user"] != user.pk and a.get("byId") != user.pk and not can_manage_absences(user):
            raise ApiError("FORBIDDEN_PERMISSION", "Vous ne pouvez pas retirer cette absence.", status.HTTP_403_FORBIDDEN)
        _save_absences(user.tenant, row, [x for x in data if x.get("id") != aid])
        audit.record(user, f"Absence {aid}", "Absence retirée", f"{a['start']} → {a['end']}", "", tenant=user.tenant)
        return Response(status=status.HTTP_204_NO_CONTENT)
