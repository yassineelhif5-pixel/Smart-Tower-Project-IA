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

## SaaS multi-tenant, offres et licences (version 1.3.0)

- **Un tenant par entreprise cliente**, données totalement isolées : `MULTI_TENANT_ARCHITECTURE.md`, preuves dans `TENANT_ISOLATION.md`.
- **Pilote (Super Admin Global)** : console « Pilote » (tableau de bord, entreprises, offres, demandes, journal, base de données).
- **Administrateur d'entreprise** : Configuration (comptes, licences et demandes, matrice des droits, délégations, API, notifications, journal).
- **Offres, abonnements, licences nominatives et concurrentes, demandes d'approbation** : `LICENSING.md`.
- **Utilisateur** : page « Mon accès » (entreprise, licence, validité, rôle, droits, session).
- API : `API_DOCUMENTATION.md` ; sécurité et audit : `SECURITY.md` ; état d'avancement : `IMPLEMENTATION_STATUS.md`.
- **Mise en ligne sur Vercel avec Supabase** : `DEPLOYMENT.md`.

## Pilotage Cycle en V et Scrum (version 1.5.0)

Capacité réelle des équipes, semaines et Weekly Goals, Product Backlog, sprints, cérémonies, rétrospectives et actions d'amélioration. Voir `METHODOLOGY.md`.

## Calendrier et collaboration (version 1.4.0)

Calendrier intelligent (9 vues, conflits expliqués, charge, rappels, abonnement ICS) et discussions de projet internes ou Microsoft Teams. Voir `CALENDAR.md` et `TEAMS_INTEGRATION.md`.

## Architecture cible (migration en cours)

L'application passe progressivement de `index.html` à une architecture SaaS :

| Partie | Technologie | Dossier |
|---|---|---|
| Interface | React + TypeScript (Vite) | `frontend/` |
| API | Django + Django REST Framework | `backend/` |
| Base | PostgreSQL (Supabase en production, base locale en développement) | via `DATABASE_URL` |

**Règle : le navigateur n'accède aux données que par l'API Django.** React n'utilise ni `supabase-js`, ni l'URL de la base, ni aucune clé. Seul Django se connecte à PostgreSQL, et c'est lui qui vérifie les droits à chaque requête.

Ce qui est déjà migré : la connexion (session + CSRF, mot de passe provisoire à changer) et le module **Configuration**, réservé aux administrateurs. Toutes les données métier ont leurs tables Django (lot 2b, voir `DATABASE.md`), mais les écrans correspondants sont encore dans `index.html`.

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
python manage.py load_demo                        # facultatif : données de démonstration (supabase/seed.sql)
python manage.py create_default_admin             # admin / admin du tenant « Demo ESN », à changer à la 1re connexion
python manage.py create_pilot pilote               # Pilote (Super Admin Global) : mot de passe provisoire affiché une fois
python manage.py runserver
```

Maintenance à planifier en production :
- `python manage.py expire_licenses` toutes les 5 minutes (sessions inactives, abonnements échus) ;
- `python manage.py purge_logs` une fois par jour (durées de conservation ; `--dry-run` pour simuler) ;
- `python manage.py check_tenants` après tout import ou restauration (cohérence entre entreprises).

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
| `LICENSE_SESSION_IDLE_MINUTES` | Inactivité après laquelle une session rend sa licence concurrente (30 par défaut). |
| `TRUST_X_FORWARDED_FOR` | `true` seulement derrière un reverse proxy de confiance (adresse IP du journal d'audit). Automatique sur Vercel. |
| `DB_CONN_MAX_AGE` | Durée de vie des connexions à la base, en secondes (60 par défaut ; 0 sur Vercel). |
| `CRON_SECRET` | Jeton de la maintenance planifiée `/api/v1/cron/maintenance` (vide : route désactivée). |
| `PUBLIC_BASE_URL` | Adresse publique https (Teams : retour OAuth, liens, notifications). Vide : relecture périodique. |

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

## Dossier `supabase/` (archivé)

Depuis le lot 2b, **Django est le seul propriétaire du schéma** : toutes les tables de ce dossier sont reprises dans les modèles Django (correspondance complète dans `DATABASE.md`). Le dossier reste dans le dépôt comme référence :

- `migrations/20261030220000_schema.sql` : ancien schéma et règles RLS. **Ne pas l'exécuter** sur la base qui reçoit les migrations Django.
- `seed.sql` : les données de démonstration, lues par `python manage.py load_demo`. Fichier généré : ne le modifiez pas à la main.
- `generate_seed.py` : régénère `seed.sql` depuis `index.html` (`python3 supabase/generate_seed.py`, nécessite Playwright).
- `verify_django_equivalence.py` : contrôle ponctuel que les règles de lecture Django donnent les mêmes lignes que les RLS (mode d'emploi en tête du fichier).
