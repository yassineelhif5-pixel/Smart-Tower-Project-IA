# Architecture multi-tenant

Mis à jour le 2026-11-01 (version 1.3.0).

## Principe

Un client SaaS = un tenant (`tenants.Tenant`). La plateforme utilise **une base PostgreSQL mutualisée avec isolation logique** : chaque table métier, de configuration et de licences porte une colonne `tenant`. Le tenant d'une requête est **toujours déduit côté serveur de l'utilisateur connecté** (`request.user.tenant`) ; aucune API n'accepte un identifiant de tenant venant du navigateur.

## Profils

| Profil | Tenant | Peut | Ne peut pas |
| --- | --- | --- | --- |
| Pilote (Super Admin Global, rôle `superadmin`) | aucun | créer et suspendre des entreprises, gérer offres, versions, abonnements, contrats, stock de licences, décider et exécuter les demandes, consulter le tableau de bord et le journal de la plateforme, l'état de la base | lire les données métier privées d'une entreprise (projets, tâches, documents…), utiliser l'administration d'un tenant |
| Administrateur tenant (`admin`) | le sien | gérer comptes, rôles, droits, délégations, licences, sessions, demandes, secrets et notifications de son entreprise | toucher aux offres, prix, contrats, stock ; approuver ses demandes ; voir un autre tenant ; accéder aux paramètres globaux |
| Responsable de licences (`license_manager`) | le sien | affecter, libérer, réaffecter des licences ; voir les sessions ; créer et annuler des demandes | administrer les comptes et les droits |
| Manager, Direction, Chef de projet, Consultant, Développeur, Testeur, Commercial, Tech Lead | le sien | selon la matrice métier et les droits délégués | — |
| Client (portail) | le sien | ses projets, ses tâches et les éléments marqués visibles par le client | les données internes |
| Lecture seule (`readonly`) | le sien | consulter les modules métier | toute modification |

Le Pilote se crée uniquement en ligne de commande (`python manage.py create_pilot <identifiant>`) : aucune API ne permet d'en créer un ni d'attribuer ce rôle.

## Résolution et contrôles

1. **Connexion** : un compte d'un tenant suspendu, désactivé ou archivé est refusé (`TENANT_INACTIVE`) ; puis la licence est réservée (voir `LICENSING.md`).
2. **Chaque requête** passe par trois contrôles DRF : `TenantIsActive`, `LicenseIsValid` (abonnement valide, session toujours titulaire de sa licence), `PasswordChangeNotRequired`.
3. **Lecture** : toute donnée métier passe par `projects.access` (`visible_projects`, `visible_actions`, `visible(user, Modèle)`), qui commence par filtrer sur le tenant de l'utilisateur.
4. **Administration** : `AdminView` limite chaque requête au tenant de l'administrateur ; un objet d'un autre tenant répond 404, sans révéler son existence.
5. **Écriture** : `TenantOwned.save()` reprend le tenant du parent et refuse un parent d'un autre tenant ; un signal refuse les relations plusieurs-à-plusieurs entre tenants (`CrossTenantError`).
6. **Contrôle a posteriori** : `python manage.py check_tenants` vérifie toutes les relations de toutes les tables portant un tenant (code de sortie 1 en cas d'écart).

## Données propres à chaque tenant

Comptes, matrice des droits (copie du modèle à la création), droits délégués, secrets (SMTP, webhooks), canaux et règles de notification, réglages métier, jetons API, journaux d'audit et d'appels, abonnements, stock, licences, affectations, sessions, demandes.

## Cycle de vie d'une entreprise

`active` ⇄ `suspended` → `disabled` → `archived` (réactivation possible depuis `suspended` et `disabled` ; `archived` → `disabled` seulement). Un motif est obligatoire hors réactivation. **Aucun statut ne supprime de données.**

## Existant (avant le multi-tenant)

Toutes les données antérieures sont rattachées au tenant « Demo ESN » (`demo-esn`), renommable par le Pilote. Ce tenant n'a pas d'abonnement : il n'est pas soumis aux licences tant que le Pilote ne lui en attribue pas un.

## Limites connues et suite

- **Seconde barrière RLS PostgreSQL** : non encore en place. L'isolation repose sur le code applicatif (contrôles ci-dessus, 23 tests d'accès croisé). Prévu : paramètre de session `app.tenant_id` posé par Django et politiques RLS par table.
- **Un utilisateur dans plusieurs tenants** : non pris en charge (un compte = un tenant). Prévu : appartenances distinctes avec sélection explicite du tenant.
- **Base dédiée pour les clients Enterprise** : non implémentée. La stratégie retenue (base mutualisée, colonne `tenant`) la rend possible plus tard par un routeur de bases, sans changer le modèle.
- **Accès de support exceptionnel du Pilote** (justifié, limité dans le temps, audité) : non implémenté ; aujourd'hui le Pilote n'a aucun accès aux données métier.
- **Identifiants de connexion** uniques sur toute la plateforme (deux entreprises ne peuvent pas avoir le même identifiant).
