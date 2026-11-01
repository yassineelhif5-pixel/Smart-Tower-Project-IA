# État d'implémentation — Project Control Tower

Mis à jour le 2026-11-01, à la fin du **lot 2a (stabilisation)**. Référence : audit de la phase 1 et cahier des charges « Prompt maître global ».

## Décisions validées (audit phase 1)

1. Django est le seul propriétaire du schéma ; le SQL Supabase est porté en migrations Django puis archivé. Supabase reste l'hébergeur PostgreSQL.
2. Multi-tenant en base PostgreSQL mutualisée : une colonne `tenant` sur chaque table métier, filtrage serveur automatique, RLS en seconde barrière.
3. Ordre : stabilisation, schéma unique, multi-tenant, puis pages métier, avant tout nouveau module ou agent IA.

## Fonctionnalités

| Fonctionnalité | État | Où |
| --- | --- | --- |
| Connexion, session, CSRF, mot de passe provisoire | Opérationnelle | Django + React |
| Limite de connexion (10/min) partagée entre processus | Corrigée (lot 2a) | Django, cache PostgreSQL |
| Comptes, rôles, matrice des droits, affectations | Opérationnelle | Django + React |
| Jetons API, secrets chiffrés | Opérationnelle | Django + React |
| Rotation de la clé de chiffrement | Développée (lot 2a) | `rotate_secrets` |
| Journal d'audit et journal API | Améliorée (lot 2a) : purge planifiable | `purge_logs` |
| API versionnée `/api/v1/` | Développée (lot 2a) ; `/api/` conservé | Django |
| Documentation OpenAPI / Swagger | Partielle (lot 2a) : 30 chemins décrits, corps des écritures pas encore détaillés | `/api/v1/schema`, `/api/v1/docs` |
| Notifications in-app, SMTP, Teams, Slack | Partielle : un seul événement émis (changement de périmètre) | Django + React |
| Liste des projets et tâches selon le périmètre | Partielle : API en lecture, sans écran React | Django |
| Tableaux de bord, planning, budget, temps, risques, tests, documents, reporting | Démo uniquement | `index.html` |
| Assistant IA filtré par profil | Démo, filtrage côté navigateur | `index.html` |
| Multi-tenant, super administrateur, abonnements | Absente — lot 3 | — |
| Carte projet, versions, releases, exigences, agents IA | Absente — lots 4 et 5 | — |

## Tests exécutés (lot 2a)

| Contrôle | Résultat |
| --- | --- |
| `manage.py check` | Aucun problème |
| `makemigrations --check` | Aucune migration manquante |
| `manage.py test` | 49 tests réussis (38 existants + 11 nouveaux) |
| Migration sur base vide, `load_demo`, `purge_logs`, `rotate_secrets` | Réussis ; table `pct_cache` créée |
| `spectacular --validate` | Schéma généré ; avertissements « serializer non deviné » sur les vues sans sérialiseur (documentées sans corps) |
| Frontend : typecheck, lint, format, 6 tests, build | Réussis |

## Fichiers modifiés (lot 2a)

- Ajoutés : `backend/config/openapi.py`, `backend/configuration/management/commands/purge_logs.py`, `backend/configuration/management/commands/rotate_secrets.py` (+ `__init__.py`), `backend/configuration/migrations/0003_cache_table.py`, `backend/configuration/test_stabilisation.py`, `CHANGELOG.md`, `IMPLEMENTATION_STATUS.md`.
- Modifiés : `backend/config/settings.py`, `backend/config/urls.py`, `backend/config/env.py`, `backend/configuration/crypto.py`, `backend/configuration/views.py` (liste des routes), `backend/configuration/tests.py` (chemins `/api/v1/` attendus), `backend/requirements.txt` (drf-spectacular), `backend/.env.example`, `frontend/src/api/client.ts`, `frontend/src/api/client.test.ts`, `frontend/.gitignore`, `README.md`.
- Supprimés : `.github/workflows/jekyll-docker.yml`, `frontend/tsconfig.tsbuildinfo`.

Tables : `pct_cache` (cache partagé) créée. Aucune table métier modifiée, aucune donnée supprimée.

## Problèmes restants

- Les corps de requête et de réponse ne sont pas encore décrits dans OpenAPI (vues sans sérialiseur). À compléter au fil des lots, route par route.
- `purge_logs` doit être planifié (tâche cron ou planificateur de l'hébergeur) : rien ne le lance automatiquement.
- Les risques « droits appliqués dans le navigateur » et « assistant IA filtré par mots-clés » de la démo restent ouverts : ils disparaissent avec la migration des pages (lot 4a) et les agents serveur (lot 5).

## Prochaines actions

- **Lot 2b — schéma unique** : porter les tables métier du SQL Supabase en modèles et migrations Django, données de démo comprises, sans perte.
- Puis **lot 3 — multi-tenant**.
