# Base de données — Project Control Tower

Mis à jour le 2026-11-01 (version 1.3.0 : schéma unique, multi-tenant, offres et licences).

**Règle** : Django est le seul propriétaire du schéma. Toute évolution passe par `python manage.py makemigrations`, relue puis committée, puis `python manage.py migrate`. Supabase n'est que l'hébergeur PostgreSQL. Le fichier `supabase/migrations/20261030220000_schema.sql` est archivé : il ne doit pas être exécuté sur la base qui reçoit les migrations Django.

## Applications et tables

| Application | Modèles | Rôle |
| --- | --- | --- |
| `tenants` | `Tenant` | Entreprises clientes (un tenant par client) |
| `accounts` | `User` (+ `tenant`), `Role`, `RolePermission` (+ `tenant`), `RoleCapability`, `UserCapability` | Comptes, rôles, matrice métier par tenant, droits d'administration délégués |
| `projects` | voir la correspondance ci-dessous ; tous héritent de `TenantOwned` (colonne `tenant`) | Données métier |
| `configuration` | `ServiceSecret`, `ApiToken`, `ApiRequestLog`, `NotificationChannel`, `NotificationRule`, `Notification`, `AuditEvent`, `AppSetting` — tous rattachés à un tenant | Administration, journaux, réglages |
| `licensing` | `Offer`, `OfferVersion`, `Contract`, `Subscription`, `LicenseAllocation`, `License`, `LicenseAssignment`, `ConcurrentSession`, `LicenseRequest`, `LicenseRequestEvent` | Offres, abonnements, licences, demandes (`LICENSING.md`) |

Une table de cache partagé, `pct_cache`, est créée par la migration `configuration/0003` (compteur de tentatives de connexion).

## Correspondance Supabase → Django

Les 25 tables du schéma Supabase ont toutes un équivalent. Aucune colonne n'a été abandonnée.

| Table Supabase | Modèle Django | Remarques |
| --- | --- | --- |
| `roles` | `accounts.Role` | `id` → `code` |
| `role_permissions` | `accounts.RolePermission` | Identique |
| `people` | `accounts.User` | `id` → `person_code` ; `is_virtual` → `is_active = False` ; `auth_user_id` remplacé par la connexion Django |
| `people_internal` | `projects.PersonCapacity` | Lien un-à-un avec l'utilisateur |
| `clients` | `projects.Client` | `id` → `code` ; `managers`, `sales` deviennent des relations vers les utilisateurs |
| `client_contracts` | `projects.ClientContract` | |
| `projects` | `projects.Project` | `team` devient une relation ; colonnes jsonb en JSONField |
| `project_internal` | `projects.ProjectInternal` | |
| `project_finance` | `projects.ProjectFinance` | Montants en décimal |
| `actions` | `projects.Action` | `us` devient une clé vers `UserStory` |
| `action_comments` | `projects.ActionComment` | |
| `user_stories` | `projects.UserStory` | |
| `objectives` | `projects.Objective` | `project` facultatif (objectif d'équipe ou personnel) |
| `todos` | `projects.Todo` | |
| `time_entries` | `projects.TimeEntry` | Heures > 0 (contrainte), index par personne et date, et par projet |
| `risks` | `projects.Risk` | `actions` devient une relation vers `Action` |
| `issues` | `projects.Issue` | |
| `change_requests` | `projects.ChangeRequest` | |
| `change_request_amounts` | `projects.ChangeRequestAmount` | Montant séparé, pour en limiter la lecture |
| `test_campaigns` | `projects.TestCampaign` | `pass` → `passed` (mot réservé de Python ; colonne SQL `pass` conservée) |
| `defects` | `projects.Defect` | |
| `documents` | `projects.Document` | Fiche uniquement : le stockage réel des fichiers viendra avec la GED |
| `meetings` | `projects.Meeting` | `attendees`, `actions` deviennent des relations ; `doc` une clé vers `Document` |
| `audit_log` | `configuration.AuditEvent` | Historique de démo importé par `load_demo` |
| `app_settings` | `configuration.AppSetting` | |

Conventions : une colonne jsonb devient un `JSONField` ; une liste de libellés (`skills`, `external`, `agenda`, `decisions`) une liste JSON ; une liste d'identifiants une relation, pour que la base garantisse leur existence ; montants et heures en `DecimalField`, jamais en flottant.

## Règles de lecture

Les politiques RLS Supabase sont reprises dans `backend/projects/access.py` : `visible(user, Modèle)` renvoie les lignes qu'un utilisateur peut lire. Toute future API part de cette fonction ; un modèle sans règle est refusé.

Vérification faite le 2026-11-01 avec `supabase/verify_django_equivalence.py`, sur une copie locale du schéma Supabase et les données de démonstration : 280 contrôles (20 tables × 14 personnes actives), **0 écart** entre les RLS et Django.

Différence assumée : dans Supabase, le périmètre d'un utilisateur se déduit de son rôle (manager d'un client, chef de projet…). Dans Django, il est donné par des affectations explicites (`ProjectAccess`), gérées dans le module Configuration, conformément au cahier des charges (« projets affectés ou accès explicite »). Les données de démo traduisent l'un en l'autre.

## Données de démonstration

`python manage.py load_demo` lit `supabase/seed.sql` (1 907 lignes) et `backend/projects/fixtures/demo.json` (identifiants de connexion et périmètres). Il est idempotent : relancé, il met à jour les fiches de démonstration sans créer de doublon, et ne supprime jamais rien. Ces données ne doivent jamais être chargées dans la base d'un client.

`seed.sql` reste généré par `supabase/generate_seed.py` à partir de `index.html` ; le lecteur `projects/seed_sql.py` refuse tout format inattendu plutôt que de perdre une valeur.

## Migrations du lot 2b

| Migration | Contenu |
| --- | --- |
| `projects/0002_metier_supabase` | 17 nouveaux modèles et 6 tables de liaison ; 25 colonnes ajoutées (2 sur `Client`, 10 sur `Project`, 13 sur `Action`). Aucune colonne supprimée ni modifiée. |
| `configuration/0004_app_settings` | Table `AppSetting` |

Les lignes existantes traversent la migration intactes (test `MigrationKeepsDataTests`) ; les nouvelles colonnes y prennent une valeur vide.

## Migrations du lot 3a et des phases 3 à 5 (multi-tenant, profils, licences)

| Migration | Contenu |
| --- | --- |
| `tenants/0001`, `0002` | Table `Tenant` ; tenant « Demo ESN » qui reçoit toutes les données existantes |
| `accounts/0004`, `0005` | `User.tenant`, `RolePermission.tenant` ; comptes rattachés à Demo ESN ; rôle Pilote ; copie de la matrice par tenant |
| `configuration/0005` | Secrets, canaux et réglages : identifiant numérique + tenant, unicité par tenant ; règles de notification par type de canal ; tenant sur jetons, journaux. **Non réversible (clés primaires changées) : sauvegarde avant application.** |
| `projects/0003` à `0005` | Colonne `tenant` sur les 22 modèles métier (ajout, remplissage avec Demo ESN, puis obligatoire) ; code projet unique par tenant |
| `accounts/0006`, `0007` | Droits d'administration délégables ; profils Responsable de licences et Lecture seule |
| `licensing/0001`, `0002` | Tables des offres et licences ; offres de départ Demo (publiée), Starter, Pro, Enterprise (brouillons) |
| `configuration/0006` | Journal d'audit : adresse IP, résultat, date fixable à la création, **déclencheur refusant toute modification** |

Vérifié : montée de version d'une base au format du lot 2b, avec données de démo, secret, canal, jeton et journaux. Toutes les lignes sont conservées et rattachées à Demo ESN ; le secret reste lisible.
