"""Point d'entrée Vercel du backend Django (fonction Python serverless).

Toutes les requêtes /api/… sont réécrites vers cette fonction (vercel.json) ; Django reçoit le chemin d'origine
(/api/v1/…). Le code du backend est embarqué avec la fonction (functions.includeFiles = backend/**).
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

app = get_wsgi_application()
