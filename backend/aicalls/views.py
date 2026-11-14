"""API des appels IA : /projects/<id>/ai-calls et /projects/<id>/ai-calls/<call_id>."""
import re
import secrets
import unicodedata
from decimal import Decimal

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.errors import ApiError
from configuration import audit
from projects.ai_orchestrator import ROSTER, team_conf
from projects.assistant import mode_of
from projects.models import Document
from projects.workspace import _project

from . import engine
from .docgen import build_docx
from .models import AiCall
from .templates import CALL_ROLES, DOC_TYPE_LABEL, TEMPLATES

LEADS = [c for c, r in CALL_ROLES.items() if r["doc"] in TEMPLATES]


def _enabled(project):
    conf = team_conf(project)
    return {c for c, a in conf["assistants"].items() if a["enabled"]} | {"maestro"}


def _guard(request, pk):
    project = _project(request.user, pk)
    if not team_conf(project)["licensed"]:
        raise ApiError("FORBIDDEN_PERMISSION", "L'entreprise n'a pas de licence Assistants IA (à demander au Pilote).",
                       status.HTTP_403_FORBIDDEN)
    if mode_of(request.user) == "off":
        raise ApiError("FORBIDDEN_PERMISSION", "Votre profil n'a pas accès aux assistants IA (à activer par l'administrateur).",
                       status.HTTP_403_FORBIDDEN)
    return project


def _mate(code, enabled):
    r = ROSTER.get(code, {})
    return {"code": code, "name": r.get("name", code), "role": r.get("role", ""), "avatar": r.get("avatar", ""),
            "color": r.get("color", "#4f46e5"), "mission": r.get("mission", ""), "enabled": code in enabled,
            "canLead": code in LEADS, "docType": CALL_ROLES.get(code, {}).get("doc"),
            "docLabel": DOC_TYPE_LABEL.get(CALL_ROLES.get(code, {}).get("doc") or "", "")}


def _duration(call):
    end = call.ended_at or timezone.now()
    return max(1, round((end - call.started_at).total_seconds() / 60))


def _summary(call):
    return {"id": call.id, "status": call.status, "mode": call.mode, "objective": call.objective, "docTitle": call.doc_title,
            "lead": call.lead, "leadName": engine.name_of(call.lead), "startedAt": call.started_at, "endedAt": call.ended_at,
            "duration": _duration(call), "organizer": call.organizer.display_name if call.organizer_id else "",
            "turns": len(call.turns), "stopped": bool(call.state.get("stopped")), "document": {"id": call.document_id, "name": call.document.name, "version": call.document.version}
            if call.document_id else None}


def _full(call, enabled):
    return {**_summary(call), "assistants": [_mate(c, enabled) for c in call.assistants], "participants": call.participants,
            "docType": call.doc_type, "docLabel": DOC_TYPE_LABEL.get(call.doc_type, ""), "sections": call.sections,
            "turns": call.turns[-300:], "cards": call.cards, "files": call.files,
            "llm": bool(call.state.get("llm")), "promptVersion": call.state.get("prompt"), "cursor": call.state.get("cursor"),
            "projectId": call.project_id, "projectCode": call.project.code}


def _join(call, user):
    if not any(p["id"] == user.pk for p in call.participants):
        call.participants = call.participants + [{"id": user.pk, "name": user.display_name,
                                                  "role": user.role.label if user.role else "", "at": timezone.now().isoformat()}]
        return True
    return False


class AiCallsView(APIView):
    def get(self, request, pk):
        project = _guard(request, pk)
        enabled = _enabled(project)
        has_specs = Document.objects.filter(project=project, type="specs").exists()
        calls = AiCall.objects.filter(project=project).select_related("organizer", "document")[:30]
        return Response({"assistants": [_mate(c, enabled) for c in CALL_ROLES], "calls": [_summary(c) for c in calls],
                         "hasSpecs": has_specs, "isPm": project.pm_id == request.user.pk or request.user.is_app_admin,
                         "speechProvider": "browser"})

    def post(self, request, pk):
        project = _guard(request, pk)
        enabled = _enabled(project)
        lead = str(request.data.get("lead") or "nova")
        if lead not in LEADS:
            raise ApiError("VALIDATION_ERROR", "Choisissez l'assistant qui rédige le document.")
        if lead not in enabled:
            raise ApiError("FORBIDDEN_PERMISSION", f"{engine.name_of(lead)} n'est pas activé sur ce projet "
                           "(Orchestrateur IA → paramètres, dans la limite de la licence).", status.HTTP_403_FORBIDDEN)
        extra = [c for c in (request.data.get("assistants") or []) if c in CALL_ROLES and c in enabled and c not in ("maestro", lead)]
        doc_type = CALL_ROLES[lead]["doc"]
        title = (str(request.data.get("docTitle") or "").strip() or f"{TEMPLATES[doc_type]['title']} - {project.name}")[:200]
        call = AiCall(id=f"AC{secrets.token_hex(5).upper()}", tenant=project.tenant, project=project, organizer=request.user,
                      mode="video" if request.data.get("mode") == "video" else "audio",
                      objective=str(request.data.get("objective") or "")[:300], assistants=["maestro", lead] + extra,
                      lead=lead, doc_type=doc_type, doc_title=title)
        _join(call, request.user)
        specs = Document.objects.filter(project=project, type="specs").order_by("-uploaded_at").first() if doc_type == "sfd" else None
        engine.start(call, request.user, specs)
        call.save()
        audit.record(request.user, f"Projet {project.code}", "Appel IA ouvert", "", f"{engine.name_of(lead)} · {title}",
                     tenant=request.user.tenant)
        return Response(_full(call, enabled), status=status.HTTP_201_CREATED)


class AiCallDetailView(APIView):
    def get(self, request, pk, call_id):
        project = _guard(request, pk)
        call = get_object_or_404(AiCall.objects.select_related("project", "organizer", "document"), project=project, pk=call_id)
        return Response(_full(call, _enabled(project)))

    def post(self, request, pk, call_id):
        project = _guard(request, pk)
        enabled = _enabled(project)
        action = request.data.get("action")
        user = request.user
        with transaction.atomic():
            call = get_object_or_404(AiCall.objects.select_for_update().select_related("project"), project=project, pk=call_id)
            if action == "generate":  # appel arrêté sans document : on peut encore générer le document plus tard
                if not call.state.get("stopped") or call.document_id:
                    raise ApiError("CONFLICT", "Le document de cet appel est déjà généré.", status.HTTP_409_CONFLICT)
                self._close(call, user)
                call.state = {**call.state, "stopped": False}
                call.save()
                call.refresh_from_db()
                return Response(_full(call, enabled))
            if call.status != AiCall.LIVE and action != "join":
                raise ApiError("CONFLICT", "Cet appel est clôturé.", status.HTTP_409_CONFLICT)
            if action == "join":
                if _join(call, user) and call.status == AiCall.LIVE:
                    engine.say(call, "maestro", f"{user.display_name} rejoint l'appel.", kind="system")
            elif action == "say":
                _join(call, user)
                engine.user_turn(call, user, str(request.data.get("text") or ""), enabled)
            elif action == "card":
                card = next((c for c in call.cards if c["id"] == request.data.get("cardId")), None)
                if card is None or card["status"] != "open":
                    raise ApiError("CONFLICT", "Ce choix a déjà été traité.", status.HTTP_409_CONFLICT)
                outcome = engine.answer_card(call, user, card, str(request.data.get("optionId") or ""),
                                             str(request.data.get("text") or ""), enabled)
                if outcome == "close":
                    self._close(call, user)
                elif outcome == "stop":
                    self._stop(call, user)
            elif action == "file":
                doc = get_object_or_404(Document, project=project, pk=request.data.get("docId"))
                engine.apply_document(call, doc, user.display_name)
            elif action == "edit":
                s = engine.section(call, str(request.data.get("key") or ""))
                if s is None:
                    raise ApiError("VALIDATION_ERROR", "Section inconnue.")
                engine.write_section(call, s["key"], str(request.data.get("content") or "")[:20000], user.display_name, replace=True)
                engine.trace(call, "correction", user.display_name, f"Section « {s['title']} » modifiée à la main", call.lead)
                cur = engine.current(call)
                if cur is not None and cur["key"] == s["key"]:
                    engine.ask_next(call, call.lead, f"J'ai vu votre modification de « {s['title']} », je la garde.")
                else:
                    engine.say(call, call.lead, f"J'ai vu votre modification de « {s['title']} », je la garde.")
            elif action == "close":
                self._close(call, user)
            elif action == "stop":
                self._stop(call, user)
            else:
                raise ApiError("VALIDATION_ERROR", "Action inconnue.")
            call.save()
        call.refresh_from_db()
        return Response(_full(call, enabled))

    def _stop(self, call, user):
        """Arrêt de l'appel sans générer de document : l'échange et le brouillon restent consultables et traçés."""
        call.status = AiCall.CLOSED
        call.ended_at = timezone.now()
        call.state = {**call.state, "stopped": True}
        filled = len([s for s in call.sections if s["status"] not in ("empty", "skipped")])
        engine.say(call, "maestro", f"Appel arrêté par {user.display_name} après {_duration(call)} min, sans document. "
                                    f"Le brouillon ({filled} section(s)) reste consultable ; vous pourrez générer le document plus tard.")
        engine.trace(call, "execution", user.display_name, "Appel arrêté sans génération de document", "maestro")
        audit.record(user, f"Projet {call.project.code}", "Appel IA arrêté sans document", "", call.doc_title, tenant=user.tenant)

    def _close(self, call, user):
        project = call.project
        now = timezone.localtime()
        label = DOC_TYPE_LABEL.get(call.doc_type, "Document")
        humans = [p["name"] for p in call.participants]
        bots = [engine.name_of(c) for c in call.assistants]
        filled = [s for s in call.sections if s["status"] not in ("empty", "skipped")]
        decisions = [c for c in call.cards if c["status"] == "answered" and c["meta"].get("kind") in ("archi", "vague", "llm")]
        open_q = (engine.section(call, "questions") or {}).get("content", "")
        ctx = (engine.section(call, "contexte") or {}).get("content") or ""
        own = [l for l in ctx.splitlines() if l.strip() and not l.startswith("Repris de « ")]
        brief = " ".join((" ".join(own) or call.objective or ctx or call.doc_title).split())[:180]
        duration = _duration(call)
        name = f"{label} - {call.doc_title}"[:255]
        same = Document.objects.filter(project=project, name=name, type=call.doc_type).order_by("-version").first()
        version = (same.version + 1) if same else 1
        slug = re.sub(r"[^A-Za-z0-9]+", "-", unicodedata.normalize("NFKD", call.doc_title).encode("ascii", "ignore").decode()).strip("-")[:40]
        file_name = f"{now:%Y-%m-%d}_{project.code}_{label.replace(' ', '-')}_{slug}_v0.{version}.docx"
        meta = {
            "nom": name, "type": label, "date": now.strftime("%d/%m/%Y"), "heure": now.strftime("%H:%M"), "dureeMin": duration,
            "participants": humans + bots, "contenuBref": brief,
            "description": f"{len(filled)}/{len(call.sections)} sections rédigées, {len(decisions)} décision(s), "
                           f"{len([l for l in open_q.splitlines() if l.strip()])} question(s) ouverte(s). Appel {call.id}.",
            "motsCles": [s["title"] for s in filled][:12], "appel": call.id, "fichier": file_name, "version": f"0.{version}",
            "statut": "Brouillon", "dossier": f"Conception/{label}",
        }
        meta_lines = [f"Projet : {project.code} · {project.name}", f"Version 0.{version} · Brouillon · {meta['date']} {meta['heure']} · {duration} min",
                      "Participants : " + ", ".join(meta["participants"]), f"Rédigé en appel IA ({call.id}) par {engine.name_of(call.lead)}"]
        content = build_docx(f"{label} - {call.doc_title}", meta_lines, [(s["title"], s["content"]) for s in call.sections])
        text = "\n\n".join(f"{s['title']}\n{s['content']}" for s in call.sections)
        doc = Document.objects.create(
            tenant=project.tenant, project=project, id=f"D{secrets.token_hex(6).upper()}", name=name, ext="docx",
            type=call.doc_type if call.doc_type in ("sfd", "std", "test", "planning", "minutes") else "delivery",
            dstat="Brouillon", entity=meta["dossier"], uploaded_by=user, uploaded_at=timezone.localdate(), version=version,
            client_visible=False, content=content,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", size_bytes=len(content),
            size_mb=Decimal(len(content)) / Decimal(1024 * 1024), extracted_text=text[:200000],
            description="\n".join([f"Date : {meta['date']} {meta['heure']}", f"Durée du point : {duration} min",
                                   "Participants : " + ", ".join(meta["participants"]), f"Contenu bref : {brief}",
                                   f"Description : {meta['description']}", f"Fichier : {file_name}"]),
            extraction={"aiCall": meta, "source": "Appel IA", "suggestedType": call.doc_type})
        later = call.status == AiCall.CLOSED  # génération différée d'un appel arrêté : la durée de l'appel ne change pas
        call.document = doc
        call.status = AiCall.CLOSED
        call.ended_at = call.ended_at or timezone.now()
        engine.say(call, "maestro", (f"Document généré par {user.display_name} après l'appel. " if later else f"Appel clôturé après {duration} min. ")
                                    + f"« {name} » est déposé en version 0.{version} (brouillon) "
                                    f"dans Documents, dossier {meta['dossier']}. {len(decisions)} décision(s) tracée(s) ; "
                                    "les questions ouvertes sont dans le document.")
        engine.trace(call, "execution", "Maestro", f"Document déposé : {name} v0.{version} ({file_name})", "maestro")
        audit.record(user, f"Projet {project.code}", "Appel IA clôturé", "", f"{name} v0.{version}", tenant=user.tenant)
