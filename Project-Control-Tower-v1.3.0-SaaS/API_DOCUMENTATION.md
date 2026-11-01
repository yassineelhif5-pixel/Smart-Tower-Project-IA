# API — Project Control Tower

Mis à jour le 2026-11-01 (version 1.3.0). Description OpenAPI complète, générée depuis le code : `GET /api/v1/schema` et page Swagger `/api/v1/docs` (administrateur ou Pilote connecté).

**Règles communes**
- Préfixe `/api/v1/`. L'ancien préfixe `/api/` reste servi pour les routes antérieures au lot 3a.
- Session (cookie) + jeton CSRF, ou jeton API `Authorization: Bearer pct_…` (lecture seule par défaut ; jamais pour l'administration ni la plateforme).
- Le tenant n'est **jamais** un paramètre : il est déduit du compte connecté.
- Erreurs : `{"code", "message", "details", "traceId"}`. Codes propres au multi-tenant et aux licences : `TENANT_INACTIVE`, `SUBSCRIPTION_EXPIRED`, `SUBSCRIPTION_SUSPENDED`, `NO_LICENSE`, `LICENSE_CAPACITY_REACHED`, `SESSION_LIMIT`, `LICENSE_SESSION_ENDED`, `USER_QUOTA_REACHED`, `STOCK_IN_USE`, `LICENSE_UNAVAILABLE`, `ALREADY_LICENSED`, `VERSION_LOCKED`, `FEATURE_NOT_IN_OFFER`.

## Connexion et profil

| Route | Méthodes | Accès |
| --- | --- | --- |
| `/health` | GET | public, sans détail |
| `/auth/csrf`, `/auth/login` | GET, POST | public (10 tentatives par minute) |
| `/auth/logout`, `/auth/me`, `/auth/change-password` | POST, GET, POST | connecté |
| `/me/access` | GET | connecté : entreprise, licence, validité, rôle, droits, session |
| `/notifications` | GET, POST | connecté (ses notifications) |

## Données métier (périmètre de l'utilisateur, dans son tenant)

| Route | Méthodes |
| --- | --- |
| `/projects` | GET |
| `/projects/{id}/actions` | GET |

## Administration du tenant (administrateur de l'entreprise, en session)

| Route | Méthodes | Objet |
| --- | --- | --- |
| `/admin/users`, `/admin/users/{id}` | GET, POST, PATCH | comptes (quota d'utilisateurs de l'offre appliqué) |
| `/admin/users/{id}/reset-password` | POST | mot de passe provisoire |
| `/admin/users/{id}/access` | GET, PUT | projets et tâches affectés |
| `/admin/users/{id}/capabilities` | GET, PUT | exceptions de droits d'administration |
| `/admin/projects` | GET | projets du tenant |
| `/admin/roles`, `/admin/roles/{code}/permissions` | GET, PUT | matrice métier du tenant |
| `/admin/capabilities` | GET, PUT | droits d'administration délégués par rôle |
| `/admin/api/endpoints` | GET | catalogue des routes (administrateur ou Pilote) |
| `/admin/api/stats`, `/admin/api/logs` | GET | appels API du tenant |
| `/admin/api/tokens`, `/admin/api/tokens/{id}/revoke` | GET, POST | jetons API du tenant |
| `/admin/secrets`, `/admin/secrets/{clé}` | GET, PUT, DELETE | secrets chiffrés du tenant |
| `/admin/notifications…` | GET, PUT, POST | canaux et règles du tenant |
| `/admin/audit` | GET | journal d'audit du tenant |

## Espace entreprise — licences (selon les droits délégués)

| Route | Méthodes | Droit requis |
| --- | --- | --- |
| `/licensing/overview` | GET | `licenses.view` |
| `/licensing/licenses` | GET | `licenses.view` |
| `/licensing/licenses/{id}/assign` · `/release` · `/reassign` | POST | `licenses.assign` ; `licenses.release` pour libérer et réaffecter |
| `/licensing/sessions` | GET | `sessions.view` |
| `/licensing/sessions/{id}/revoke` | POST | `sessions.revoke` |
| `/licensing/requests` | GET, POST | `requests.view`, `requests.create` |
| `/licensing/requests/{id}` | GET | `requests.view` |
| `/licensing/requests/{id}/submit` · `/comment` · `/cancel` | POST | `requests.create` ; `requests.cancel` pour annuler |
| `/licensing/offers` | GET | `requests.create` (offres actives, sans prix) |
| `/licensing/audit` | GET | `audit.view` ; `?export=csv` exige `audit.export` |

## Espace Pilote (session uniquement)

| Route | Méthodes | Objet |
| --- | --- | --- |
| `/platform/dashboard` | GET | indicateurs globaux |
| `/platform/tenants` | GET (`?q=`, `?status=`), POST | entreprises ; création avec offre facultative et premier administrateur |
| `/platform/tenants/{id}` | GET, PATCH | fiche (comptes, sans données métier) ; nom, langue, statut + motif |
| `/platform/tenants/{id}/subscription` | GET, POST, PATCH | abonnement, historique, mouvements de stock |
| `/platform/tenants/{id}/allocations` | POST | ajout ou retrait de licences (motif obligatoire) |
| `/platform/offers`, `/platform/offers/{id}` | GET, POST, PATCH | offres |
| `/platform/offers/{id}/versions`, `/platform/versions/{id}` | POST, PATCH | versions (brouillon modifiable, publiée verrouillée) |
| `/platform/requests` | GET (`?status=`, `?tenant=`) | demandes soumises |
| `/platform/requests/{id}` · `/decide` · `/fulfil` · `/comment` | GET, POST | examen, décision, exécution |
| `/platform/audit` | GET (`?tenant=`) | journal de la plateforme ou administratif d'un tenant |
| `/admin/database`, `/admin/database/test` | GET, POST | état de la base (paramètre global) |
