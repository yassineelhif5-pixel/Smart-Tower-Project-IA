# État d'implémentation — Project Control Tower

Mis à jour le 2026-11-01 — **version 1.3.0** (SaaS multi-tenant, Pilote, offres et licences). Références : audit de la phase 1, cahier « Prompt maître global », cahier « Architecture SaaS B2B — multi-tenant, offres, licences ».

## Décisions validées

1. Django est le seul propriétaire du schéma ; Supabase reste l'hébergeur PostgreSQL.
2. Multi-tenant en base mutualisée : colonne `tenant` sur chaque table, filtrage serveur. RLS en seconde barrière : **pas encore en place**.
3. Ordre : stabilisation, schéma unique, multi-tenant, profils et permissions, offres et licences, demandes, puis pages métier et agents IA.

## Audit ciblé (statuts du cahier SaaS)

| Domaine | Statut | Constat |
| --- | --- | --- |
| Architecture (Django + DRF, React + TypeScript + Vite, PostgreSQL) | OPERATIONAL | Conservée ; nouveaux domaines `tenants`, `licensing` |
| Modèle de données | OPERATIONAL | 25 tables métier, tenant partout, contraintes d'unicité et d'intégrité ; `DATABASE.md` |
| Utilisateurs et authentification | OPERATIONAL | Session + CSRF, limitation partagée, mot de passe provisoire, licence liée à la session |
| Rôles et permissions | OPERATIONAL | Matrice métier par tenant, droits d'administration délégables, exceptions individuelles |
| Exceptions individuelles sur la matrice métier (module × action) | MISSING | Existent pour les droits d'administration seulement |
| Préparation multi-tenant | OPERATIONAL | Isolation applicative testée (23 + 29 tests) ; RLS absente (ligne suivante) |
| RLS PostgreSQL de seconde barrière | MISSING | Prévue au lot 3b |
| Utilisateur rattaché à plusieurs tenants | MISSING | Un compte = un tenant |
| Base dédiée pour Enterprise | MISSING | Rendue possible par la conception, non implémentée |
| Gestion des licences (nominatives, concurrentes) | OPERATIONAL | Règles serveur, atomicité testée sous concurrence |
| Offres, versions, contrats, abonnements | OPERATIONAL | Pilote uniquement ; versions publiées verrouillées |
| Demandes et approbations | OPERATIONAL | 9 statuts, approbation partielle, exécution distincte |
| Facturation et paiement | MISSING | Hors périmètre de ce lot |
| API | OPERATIONAL | 58 routes `/api/v1/`, OpenAPI généré (corps de requête partiellement décrits) |
| Sécurité et audit | OPERATIONAL | IP, résultat, journal non modifiable, export CSV |
| Accès de support exceptionnel du Pilote | MISSING | Le Pilote n'a aujourd'hui aucun accès aux données métier |
| Interface Pilote | OPERATIONAL | Testée dans Chrome de bout en bout |
| Interface administrateur tenant | OPERATIONAL | Comptes, licences, demandes, délégations ; testée de bout en bout |
| Interface utilisateur (« Mon accès ») | OPERATIONAL | Testée de bout en bout |
| Équipes (entité) | MISSING | Champ texte « équipe » seulement |
| Notifications des demandes par e-mail | PARTIAL | Dans l'application uniquement |
| Pages métier (tableaux de bord, planning, budget…) | DEMO_ONLY | Encore dans `index.html` ; tables Django prêtes |
| Sauvegardes et restauration | NEEDS_VALIDATION | Dépend de l'hébergeur ; procédure à valider avec vous |

## Fonctionnalités par lot

| Fonctionnalité | État |
| --- | --- |
| Lot 2a : API `/api/v1/`, OpenAPI, cache partagé, purge des journaux, rotation de clé | Livré |
| Lot 2b : schéma unique, données de démo, règles de lecture équivalentes aux RLS | Livré |
| Lot 3a : tenant, isolation, Pilote, cycle de vie des entreprises | Livré |
| Phase 3 (cahier SaaS) : profils, RBAC dynamique, délégation, tests d'élévation de privilèges | Livré |
| Phase 4 : offres, versions, contrats, abonnements, licences nominatives et concurrentes, quotas, expiration | Livré |
| Phase 5 : demandes, approbation, historique, notifications, attribution après approbation | Livré |
| Phase 6 : audit, tests multi-tenant, RBAC, licences, concurrence, sécurité, documentation | Livré, hors RLS |

## Tests réellement exécutés (2026-11-01)

| Contrôle | Résultat |
| --- | --- |
| `manage.py check`, `makemigrations --check` | Aucun problème, aucune migration manquante |
| `manage.py test` | **111 tests réussis** : 9 comptes, 25 configuration, 11 stabilisation, 4 périmètre, 10 schéma, 23 isolation multi-tenant, 29 licences |
| Test de concurrence (10 connexions, 2 licences) | Exactement 2 réservations, 5 exécutions sur 5 |
| Montée de version d'une base au format 1.2.0 | Toutes les lignes conservées, rattachées à Demo ESN, secret lisible |
| `check_tenants` (base de démo et base du parcours navigateur) | Aucune relation entre tenants |
| Équivalence avec les RLS Supabase (`verify_django_equivalence.py`) | 280 contrôles, 0 écart |
| Frontend : typecheck, lint, format, build | Sans erreur |
| Frontend : `vitest` | 11 tests réussis |
| Parcours réel dans Chrome (Django + Vite) : le Pilote crée une entreprise avec l'offre Demo → l'administrateur change son mot de passe, voit son stock, demande 5 licences → le Pilote en approuve 3 et exécute → le stock passe à 6 → « Mon accès » → l'administrateur de Demo ESN ne voit pas la nouvelle entreprise | 9 étapes réussies, 0 erreur serveur |

Défauts trouvés et corrigés par ces tests : licence perdue au changement de mot de passe ; expiration d'abonnement annulée lors d'une connexion refusée ; libellé d'accès inexact dans le catalogue des routes ; contrôle de cohérence limité aux tables métier.

## Fichiers modifiés (version 1.3.0)

- **Nouveaux domaines** : `backend/tenants/` (modèle, signaux, services, vues, commandes `create_pilot` et `check_tenants`, tests), `backend/licensing/` (modèles, services, vues, commande `expire_licenses`, tests), `backend/accounts/capabilities.py`, `backend/configuration/context.py`.
- **Migrations** : `tenants/0001-0002`, `accounts/0004-0007`, `projects/0003-0005`, `configuration/0005-0006`, `licensing/0001-0002`.
- **Modifiés** : `accounts/models.py`, `permissions.py`, `serializers.py`, `views.py`, `create_default_admin.py` ; `configuration/models.py`, `views.py`, `serializers.py`, `notify.py`, `audit.py`, `middleware.py`, `authentication.py` ; `projects/models.py`, `access.py`, `load_demo.py` ; `config/settings.py`, `urls.py`, `errors.py` ; tests existants adaptés au modèle tenant, sans affaiblir leurs vérifications.
- **Frontend** : `App.tsx`, `Shell.tsx`, `types/api.ts`, `api/endpoints.ts`, `pages/PilotPage.tsx`, `pages/MyAccessPage.tsx`, `pages/ConfigurationPage.tsx`, `features/platform/*`, `features/licensing/*`, `features/configuration/DelegationTab.tsx`, `AuditTab.tsx`, `App.routes.test.tsx`.
- **Documentation** : `README.md`, `DATABASE.md`, `MULTI_TENANT_ARCHITECTURE.md`, `TENANT_ISOLATION.md`, `LICENSING.md`, `API_DOCUMENTATION.md`, `SECURITY.md`, `CHANGELOG.md`, ce fichier, `backend/.env.example`.

## Anomalies et limites restantes

- RLS PostgreSQL de seconde barrière absente ; isolation purement applicative (testée).
- La migration `configuration/0005` n'est pas réversible : **sauvegarde obligatoire avant la mise en production**.
- OpenAPI : les corps de requête ne sont pas détaillés pour les vues sans sérialiseur.
- Le tenant Demo ESN n'a pas d'abonnement et n'est donc pas soumis aux licences, tant que le Pilote ne lui en attribue pas un.
- Identifiants de connexion uniques sur toute la plateforme.
- `expire_licenses` et `purge_logs` doivent être planifiés : rien ne les lance automatiquement.

## Prochaines étapes proposées

1. **Lot 3b** : RLS PostgreSQL (paramètre de session posé par Django), comptes multi-tenants, accès de support du Pilote limité dans le temps et audité.
2. **Lot 4a** : migration des pages métier de `index.html` vers React, sur les tables et règles de lecture déjà en place.
3. Facturation, notifications e-mail des demandes, équipes.
