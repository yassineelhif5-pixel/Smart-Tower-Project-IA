# Isolation entre entreprises — preuves

Mis à jour le 2026-11-01. Architecture : `MULTI_TENANT_ARCHITECTURE.md`.

## Points de contrôle

| Couche | Mécanisme | Fichier |
| --- | --- | --- |
| Résolution du tenant | `request.user.tenant`, jamais une valeur du navigateur | `accounts/permissions.py` |
| Tenant inactif | refus à la connexion et à chaque requête (`TENANT_INACTIVE`) | `accounts/views.py`, `TenantIsActive` |
| Lecture métier | filtrage par tenant avant toute règle de périmètre | `projects/access.py` |
| Administration | `AdminView` : requêtes limitées au tenant, 404 hors tenant | `configuration/views.py` |
| Licences | `TenantView` + contrôle `_same_tenant` dans les règles | `licensing/views.py`, `licensing/services.py` |
| Écriture | `TenantOwned.save()`, signal plusieurs-à-plusieurs | `tenants/models.py`, `tenants/signals.py` |
| Contraintes en base | unicité par tenant (code projet, secret, canal, règle, réglage, matrice) | migrations |
| Contrôle a posteriori | `python manage.py check_tenants` | `tenants/management/commands/check_tenants.py` |

## Tests d'accès croisé (exécutés à chaque `manage.py test`)

`tenants/tests.py` (23 tests) et `licensing/tests.py` (29 tests) créent au moins deux entreprises et vérifient notamment :

- projets et tâches d'une autre entreprise invisibles, y compris pour Direction et Administrateur (404) ;
- 20 tables métier : aucune ligne d'un autre tenant via les règles de lecture ;
- le Pilote ne lit aucune donnée métier ;
- comptes, accès, matrice, secrets, notifications, jetons, journaux d'audit et d'appels : propres à chaque tenant, sans effet de l'un sur l'autre ;
- un compte créé atterrit dans le tenant de l'administrateur, même si la requête en désigne un autre ;
- client ou rôle Pilote d'un autre périmètre non attribuables ;
- liens interdits entre tenants (clé étrangère, plusieurs-à-plusieurs) et détection d'une corruption par `check_tenants` ;
- suspension d'une entreprise : bloque cette entreprise seulement ;
- licences, utilisateurs, demandes et journal d'une autre entreprise hors d'atteinte (404) ;
- export CSV du journal limité au tenant.

## Équivalence avec les règles RLS Supabase historiques

`supabase/verify_django_equivalence.py` : 280 contrôles, 0 écart (dernière exécution : 2026-11-01, après le lot 3a).
