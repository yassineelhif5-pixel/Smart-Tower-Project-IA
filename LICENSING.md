# Offres, abonnements et licences

Mis à jour le 2026-11-01 (version 1.3.0). Code : `backend/licensing/` (modèles, règles dans `services.py`, API dans `views.py`).

## Vocabulaire

| Notion | Modèle | Qui le gère |
| --- | --- | --- |
| Offre commerciale | `Offer` | Pilote |
| Version d'offre (prix, durée, essai, quotas, fonctionnalités) | `OfferVersion` | Pilote |
| Contrat | `Contract` | Pilote |
| Abonnement d'une entreprise à une version | `Subscription` | Pilote |
| Mouvement du stock de l'entreprise | `LicenseAllocation` (historique, jamais modifié) | Pilote |
| Licence (nominative ou concurrente) | `License` | créée par un mouvement de stock |
| Affectation d'une licence nominative | `LicenseAssignment` (historique) | administrateur tenant ou délégué |
| Session occupant une licence concurrente | `ConcurrentSession` | automatique |
| Demande et son historique | `LicenseRequest`, `LicenseRequestEvent` | tenant puis Pilote |

**Aucun prix ni quota n'est écrit dans le code.** Les offres de départ (Demo, Starter, Pro, Enterprise) sont des données créées par la migration `licensing/0002` : Demo est publiée avec 7 jours, 5 utilisateurs, 3 licences nominatives et 2 concurrentes (valeurs de départ à ajuster par le Pilote) ; Starter, Pro et Enterprise sont des brouillons sans prix que le Pilote complète puis publie.

Une version publiée ou déjà souscrite n'est plus modifiable (réponse 409 `VERSION_LOCKED`) : pour changer un prix, le Pilote crée une nouvelle version (copie de la précédente). Les abonnements en cours gardent leurs conditions.

## Règles appliquées par le serveur

| Règle | Où | Code d'erreur |
| --- | --- | --- |
| Un tenant n'a qu'un abonnement en cours (essai, actif ou suspendu) | contrainte `one_current_subscription` | `VALIDATION_ERROR` |
| Abonnement échu ou essai terminé : passage automatique à « Expiré » | `services.current_subscription`, commande `expire_licenses` | `SUBSCRIPTION_EXPIRED` |
| Abonnement suspendu : accès bloqué | `LicenseIsValid` | `SUBSCRIPTION_SUSPENDED` |
| Utilisateurs actifs ≤ maximum de l'offre (création et réactivation) | `check_user_quota` | `USER_QUOTA_REACHED` |
| Modules accessibles = fonctionnalités de l'offre (liste vide = tous) | `has_perm` | droit refusé |
| Délégation des droits seulement si l'offre comprend `delegation` (ou ne restreint rien) | `CapabilityMatrixView` | `FEATURE_NOT_IN_OFFER` |
| Retrait de stock limité aux licences libres | `allocate` | `STOCK_IN_USE` |
| Une licence nominative : un seul titulaire actif ; un utilisateur : une seule licence nominative | contraintes `one_holder_per_license`, `one_named_license_per_user` | `LICENSE_UNAVAILABLE`, `ALREADY_LICENSED` |
| Compte désactivé : sa licence revient au stock, ses sessions sont fermées | `release_access` | — |
| Licence concurrente : une session par licence, réservation atomique | `SELECT … FOR UPDATE SKIP LOCKED` + contrainte `one_session_per_concurrent_license` | `LICENSE_CAPACITY_REACHED` |
| Aucune licence nominative ni concurrente | `open_session` | `NO_LICENSE` |
| Connexions simultanées par utilisateur ≤ maximum de l'offre | `open_session` | `SESSION_LIMIT` |
| Session inactive au-delà de `LICENSE_SESSION_IDLE_MINUTES` (30 par défaut) : fermée, licence rendue | `expire_sessions` | `LICENSE_SESSION_ENDED` |
| Session révoquée par l'administrateur, ou licence libérée : déconnexion à la requête suivante | `LicenseIsValid` | `LICENSE_SESSION_ENDED` |

À l'expiration ou à la suspension, **aucune donnée n'est supprimée** : seul l'accès est bloqué.

Un tenant qui n'a jamais eu d'abonnement n'est pas soumis aux licences (cas de « Demo ESN », antérieur au module). Le tableau de bord du Pilote le signale comme « sans abonnement ».

Les jetons API ne consomment pas de licence concurrente, mais exigent un abonnement valide.

## Connexion et sessions

1. Identifiant et mot de passe vérifiés ; tenant actif.
2. Abonnement valide (sinon refus, et l'expiration éventuelle est enregistrée).
3. Licence : nominative si l'utilisateur en détient une ; sinon une licence concurrente libre est réservée sous verrou. La session Django et la session de licence sont liées (la licence suit la session si son identifiant change, par exemple au changement de mot de passe).
4. Déconnexion, expiration ou révocation : la licence concurrente redevient disponible.

## Demandes et approbations

Statuts : `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `ADDITIONAL_INFORMATION_REQUIRED`, `APPROVED`, `PARTIALLY_APPROVED`, `REJECTED`, `CANCELLED`, `FULFILLED`.

| Étape | Qui | Règle |
| --- | --- | --- |
| Créer, soumettre | tenant (`requests.create`) | justification obligatoire ; quantité pour licences et quota ; offre visée pour une évolution |
| Annuler | tenant (`requests.cancel`) | tant que la demande n'est pas décidée |
| Examiner, demander des informations | Pilote | commentaire obligatoire pour une demande d'informations |
| Répondre | tenant | la demande repasse à `SUBMITTED` |
| Approuver, approuver partiellement, refuser | Pilote | partiel : entre 1 et quantité − 1 ; refus : commentaire obligatoire |
| Exécuter | Pilote | licences : mouvement de stock lié à la demande ; quota, offre, option : description obligatoire de l'opération faite |

Une demande approuvée n'est pas réalisée tant qu'elle n'a pas été exécutée : le stock n'augmente qu'à l'exécution. Chaque étape est historisée (`LicenseRequestEvent`) et auditée. Le Pilote est notifié des demandes soumises ; l'entreprise, des décisions et exécutions (notifications dans l'application).

## Droits d'administration délégables

Catalogue dans `accounts/capabilities.py` : entreprise, utilisateurs, rôles et permissions, licences (consulter, attribuer, libérer), sessions (consulter, révoquer), demandes (consulter, créer, annuler), journal (consulter, exporter). Attribués par rôle et par tenant, avec exceptions individuelles (accorder ou retirer). L'administrateur garde tous les droits ; « Rôles et permissions · Administrer » ne se délègue pas ; les privilèges du Pilote ne figurent pas dans le catalogue et ne peuvent donc jamais être délégués.

## Commandes à planifier

| Commande | Fréquence conseillée | Rôle |
| --- | --- | --- |
| `python manage.py expire_licenses` | toutes les 5 minutes | ferme les sessions inactives, expire les abonnements échus |
| `python manage.py purge_logs` | quotidienne | applique les durées de conservation des journaux |
| `python manage.py check_tenants` | après tout import ou restauration | contrôle qu'aucune relation ne traverse deux tenants |

## Non couvert

Facturation et paiement (les prix sont des données de référence), notifications par e-mail des demandes (dans l'application seulement), équipes en tant qu'entité (le champ « équipe » du compte existe), exceptions individuelles sur la matrice métier (elles existent pour les droits d'administration).
