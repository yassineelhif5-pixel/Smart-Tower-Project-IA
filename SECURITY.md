# Sécurité

Mis à jour le 2026-11-01 (version 1.3.0).

## Authentification et sessions

- Session Django (cookie HttpOnly, Secure et SameSite=Lax en production, durée 8 h) et jeton CSRF ; HSTS et redirection HTTPS hors développement.
- 10 tentatives de connexion par minute, compteur partagé entre processus (cache PostgreSQL).
- Mot de passe provisoire à changer avant tout accès ; règles : 10 caractères, ni courant, ni numérique, ni proche de l'identifiant.
- Licences : une session doit détenir sa licence à chaque requête ; révocation, libération ou inactivité la déconnectent (`LICENSE_SESSION_ENDED`).
- Jetons API : empreinte SHA-256 seule stockée, affichés une fois, lecture seule par défaut, expiration, révocation, liés au tenant de leur compte ; jamais acceptés pour l'administration ni la plateforme.

## Autorisations

- Trois niveaux, tous vérifiés côté serveur : Pilote (plateforme), administrateur du tenant, droits délégués (`accounts/capabilities.py`) et matrice métier par rôle et par tenant.
- Les fonctionnalités de l'offre souscrite limitent les modules accessibles.
- L'interface adapte menus et boutons aux droits, sans que cela compte comme une protection.

## Élévation de privilèges (testée)

- Aucune API ne crée de Pilote ni n'attribue le rôle `superadmin` (création en ligne de commande uniquement).
- Un administrateur ne peut pas : modifier ses propres droits, retirer son rôle ou désactiver son compte, laisser le tenant sans administrateur actif, modifier les droits du rôle Administrateur, déléguer « Rôles et permissions », attribuer un droit hors catalogue, toucher aux offres, prix, contrats, stock, approuver ses demandes.
- Un objet d'un autre tenant répond 404 (son existence n'est pas révélée).

## Isolation multi-tenant

Voir `MULTI_TENANT_ARCHITECTURE.md`. Contrôles applicatifs à chaque requête, garde-fous à l'écriture (`TenantOwned`, signal plusieurs-à-plusieurs), commande `check_tenants`. La seconde barrière RLS PostgreSQL n'est pas encore en place.

## Concurrence

Réservation des licences concurrentes sous verrou (`SELECT … FOR UPDATE SKIP LOCKED`) et contraintes d'unicité en base. Testé avec 10 connexions simultanées pour 2 licences : exactement 2 réussissent, à chaque exécution (5 exécutions consécutives).

## Journal d'audit

- Chaque opération sensible enregistre : auteur, tenant (vide = plateforme), objet, action, ancienne et nouvelle valeur, date, adresse IP, résultat (réussi, échec, refusé), trace.
- Couverture : connexions (et refus), comptes, rôles, matrice, délégations, accès, jetons, secrets, notifications, entreprises et statuts, offres et versions, abonnements, mouvements de stock, affectations et libérations de licences, sessions révoquées, demandes et décisions, exports.
- **Protégé en base** : un déclencheur PostgreSQL refuse toute modification d'une ligne. Seule la purge planifiée (durée de conservation) supprime des lignes.
- Adresse IP : `REMOTE_ADDR`, ou premier `X-Forwarded-For` si `TRUST_X_FORWARDED_FOR=true` (uniquement derrière un reverse proxy de confiance). Le journal des appels API ne garde, lui, aucune adresse IP.
- Export CSV avec neutralisation des formules de tableur.

## Données

- Secrets chiffrés (Fernet, rotation de clé avec `rotate_secrets`), jamais renvoyés par l'API.
- Expiration d'un abonnement, suspension ou archivage d'une entreprise : **aucune suppression de données**.
- Sauvegardes : à la charge de l'hébergeur PostgreSQL (Supabase : sauvegardes quotidiennes selon l'offre). La migration `configuration/0005` n'est pas réversible : sauvegarde obligatoire avant de l'appliquer en production.
