# Project Control Tower

Démo interactive d'une application SaaS de pilotage de projets pour ESN : dashboards par profil, cycle de vie projet, planning macro, sprints et user stories, capacité en heures, saisie des temps, budget et forecast, risques, documentation, réunions, droits d'accès et assistant.

Toutes les données sont des données de démonstration, générées dans le navigateur.

## Publier sur GitHub Pages

1. Créez un dépôt (par exemple `project-control-tower`).
2. Déposez `index.html`, `.nojekyll` et `README.md` à la racine.
3. Dans **Settings → Pages**, choisissez **Deploy from a branch**, branche `main`, dossier `/ (root)`.
4. Le site est en ligne à `https://<votre-compte>.github.io/project-control-tower/` après une à deux minutes.

## Limites de la version GitHub Pages

- L'assistant IA répond en mode local (calcul sur les données de démonstration, mêmes restrictions par profil) : la rédaction par Claude n'est disponible que dans la version publiée sur claude.ai.
- Les modifications ne sont pas enregistrées côté serveur ; seuls le thème, le profil choisi et quelques paramètres restent dans le navigateur.

## Architecture cible (migration en cours)

L'application passe progressivement de `index.html` à une architecture SaaS :

| Partie | Technologie | Dossier |
|---|---|---|
| Interface | React + TypeScript (Vite) | `frontend/` |
| API | Django + Django REST Framework | `backend/` |
| Base | PostgreSQL (Supabase en production, base locale en développement) | via `DATABASE_URL` |

**Règle : le navigateur n'accède aux données que par l'API Django.** React n'utilise ni `supabase-js`, ni l'URL de la base, ni aucune clé. Seul Django se connecte à PostgreSQL, et c'est lui qui vérifie les droits à chaque requête.

Ce qui est déjà migré : la connexion (session + CSRF, mot de passe provisoire à changer) et le module **Configuration**, réservé aux administrateurs. Le reste de l'application est encore dans `index.html`.

### Module Configuration (administrateurs)

- **Utilisateurs et accès** : créer un compte (mot de passe provisoire affiché une seule fois), changer le rôle (y compris nommer un administrateur), désactiver, réinitialiser le mot de passe, affecter des projets (lecture ou écriture) et ouvrir des tâches individuellement. Il reste toujours au moins un administrateur actif, et un administrateur ne peut pas se retirer ses propres droits.
- **Matrice des droits** : droits de chaque rôle par module (voir, créer, modifier, supprimer, valider), appliqués immédiatement par l'API.
- **Base de données** : état de la connexion, version, temps de réponse, SSL, migrations en attente, test de connexion. Les identifiants restent dans `DATABASE_URL` côté serveur et ne sont jamais affichés.
- **API** : jetons d'accès pour applications tierces (empreinte SHA-256 stockée, jeton affiché une seule fois, lecture seule par défaut, expiration, révocation ; un jeton n'ouvre jamais le module Configuration), clés de services externes chiffrées (mot de passe SMTP, webhooks Teams et Slack), état des API (routes réelles, statistiques, derniers appels sans contenu ni adresse IP).
- **Notifications** : canaux dans l'application, e-mail SMTP, Teams et Slack (webhooks limités aux domaines officiels, en https), règles par événement, envoi de test.
- **Journal d'audit** : connexions, comptes, droits, accès, jetons, secrets, notifications. Aucun secret n'y est écrit.

### Prérequis

- Python 3.12 ou plus, Node.js 20 ou plus, PostgreSQL 14 ou plus (base locale de développement).

### Démarrer le backend

```bash
cd backend
python -m venv .venv && . .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                              # puis renseigner les valeurs
python manage.py migrate                          # tables, rôles et matrice par défaut
python manage.py load_demo                        # facultatif : données de démonstration
python manage.py create_default_admin             # compte admin / admin, à changer à la 1re connexion
python manage.py runserver
```

Maintenance, à planifier une fois par jour en production : `python manage.py purge_logs` (supprime les journaux plus anciens que leur durée de conservation ; `--dry-run` pour simuler).

Les comptes de démonstration (`s.mansouri`, `e.navarro`…) n'ont pas de mot de passe : un administrateur le définit avec « Réinitialiser » dans Configuration.

### Démarrer le frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 ; /api est relayé vers Django (même origine)
```

En production, servez le frontend construit (`npm run build`, dossier `dist/`) et l'API sous le **même domaine** (par exemple `/` et `/api/` derrière un reverse proxy) : la session repose sur un cookie et le jeton CSRF.

### Variables d'environnement (backend)

| Variable | Rôle |
|---|---|
| `DJANGO_SECRET_KEY` | Clé secrète Django (obligatoire). |
| `DJANGO_DEBUG` | `true` en développement uniquement. |
| `DJANGO_ALLOWED_HOSTS` | Noms de domaine servis. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Origines autorisées (https://…). |
| `DATABASE_URL` | `postgresql://utilisateur:motdepasse@hôte:port/base` (obligatoire). |
| `FIELD_ENCRYPTION_KEY` | Clé Fernet de chiffrement des secrets du module Configuration (obligatoire). Pour en changer : `nouvelle,ancienne`, puis `python manage.py rotate_secrets`, puis retirer l'ancienne. |
| `API_LOG_RETENTION_DAYS` | Conservation du journal des appels API, en jours (90 par défaut). |
| `AUDIT_LOG_RETENTION_DAYS` | Conservation du journal d'audit, en jours (365 par défaut, minimum 30). |

Le démarrage échoue avec un message qui nomme la variable manquante, sans jamais afficher de valeur. Modèle : `backend/.env.example`. Le fichier `.env` n'est jamais committé.

### Supabase côté serveur

Supabase n'est utilisé que comme hébergeur PostgreSQL, par Django. Pour pointer le backend vers Supabase : copiez la chaîne de connexion (Project Settings → Database), ajoutez `?sslmode=require`, placez-la dans `DATABASE_URL` côté serveur, puis `python manage.py migrate`. Les tests refusent de tourner sur une base Supabase.

Décision validée (audit phase 1) : **Django est le seul propriétaire du schéma.** Le schéma SQL du dossier `supabase/` est une référence, portée progressivement en migrations Django (lot 2b), puis archivée. Ne lancez pas ce fichier SQL sur la base qui reçoit les migrations Django.

### Tests et vérifications

```bash
cd backend && python manage.py test && python manage.py check && python manage.py makemigrations --check --dry-run
cd frontend && npm run typecheck && npm run lint && npm run format:check && npm test && npm run build
```

Les tests backend créent une base de test temporaire sur le serveur PostgreSQL de `DATABASE_URL` et n'appellent aucun service externe (SMTP et webhooks sont simulés).

### Procédure de migration

Les évolutions de schéma passent par les migrations Django (`python manage.py makemigrations`, relues puis committées, puis `python manage.py migrate`). Les rôles, la matrice des droits par défaut et les canaux de notification sont créés par des migrations de données.

### Principales routes de l'API

| Route | Accès |
|---|---|
| `GET /api/health` | public (sans détail) |
| `GET /api/auth/csrf`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, `POST /api/auth/change-password` | connexion |
| `GET /api/projects`, `GET /api/projects/{id}/actions`, `GET/POST /api/notifications` | connecté, selon son périmètre |
| `/api/admin/users…`, `/api/admin/roles…`, `/api/admin/database…`, `/api/admin/api/…`, `/api/admin/secrets…`, `/api/admin/notifications…`, `/api/admin/audit` | administrateur, en session |

Toutes les routes sont servies sous **`/api/v1/`** (version courante, utilisée par le frontend). L'ancien chemin `/api/` sans version reste servi à l'identique pour les applications tierces. Documentation OpenAPI pour les administrateurs connectés : `GET /api/v1/schema` et page Swagger `/api/v1/docs`.

Toutes les erreurs ont la même forme : `{"code", "message", "details", "traceId"}`.

## Schéma SQL Supabase initial


Le dossier `supabase/` contient la base qui remplacera les données de démonstration :

- `migrations/20261030220000_schema.sql` : tables, fonctions de droits (`app.*`) et règles RLS. Les droits de la page (rôle, périmètre, matrice des droits) sont appliqués par la base : un utilisateur ne reçoit que ce qu'il a le droit de voir, et un visiteur non connecté ne reçoit rien.
- `seed.sql` : les données de démonstration actuelles. Ce fichier est généré : ne le modifiez pas à la main.
- `generate_seed.py` : régénère `seed.sql` depuis `index.html` (`python3 supabase/generate_seed.py`, nécessite Playwright).

Pour créer la base sur un projet Supabase :

1. Exécutez `migrations/20261030220000_schema.sql`, puis `seed.sql` (éditeur SQL de Supabase, ou `supabase db reset` avec la CLI).
2. Créez les comptes dans **Authentication → Users** avec les e-mails de la table `people`. Chaque compte est relié automatiquement à sa fiche.
