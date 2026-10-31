from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from .access import can_edit_project, visible_actions, visible_projects


def project_row(p, user=None):
    row = {"id": p.id, "code": p.code, "name": p.name, "client": {"code": p.client_id, "name": p.client.name},
           "method": p.method, "progress": p.progress}
    if user is not None:
        row["canEdit"] = can_edit_project(user, p)
    return row


def action_row(a):
    return {"id": a.id, "project": a.project_id, "title": a.title, "status": a.status, "type": a.type,
            "owner": a.owner.display_name if a.owner else None, "due": a.due}


class ProjectListView(APIView):
    """Projets du périmètre de l'utilisateur connecté."""

    def get(self, request):
        projects = visible_projects(request.user).select_related("client")
        return Response([project_row(p, request.user) for p in projects])


class ProjectActionsView(APIView):
    """Tâches visibles d'un projet du périmètre."""

    def get(self, request, pk):
        project = get_object_or_404(visible_projects(request.user), pk=pk)
        actions = visible_actions(request.user).filter(project=project).select_related("owner")
        return Response([action_row(a) for a in actions])
