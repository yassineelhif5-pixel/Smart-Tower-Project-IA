# Discussions et Microsoft Teams (1.4.0)

## Discussions
Une discussion (`collaboration.ProjectDiscussion`) appartient à un projet et éventuellement à une action. Destination : **interne**, **Teams** ou **les deux**. Messages : réponses, mentions (personnes ayant accès au projet), pièces jointes (documents du projet visibles), modification et suppression de **ses** messages avec historique, état de publication (interne, en cours, publié, échec + raison, renvoi). Clé d'idempotence côté navigateur : un double clic ne crée pas deux messages.
Visibilité : discussion interne ou de canal → toute personne qui voit le projet (et l'action) avec le droit « Collaboration · Voir » ; conversation individuelle ou de groupe → ses seuls participants (même l'administrateur du tenant ne la lit pas). **Le Pilote n'a accès à aucune discussion.**
Les commentaires d'actions existants ont été repris dans des discussions internes (migration `collaboration/0002`, originaux conservés).

## Connecteur (un par tenant)
Configuration → Connecteurs (administrateur) : identifiant de l'annuaire Microsoft Entra, identifiant client, secret client (chiffré Fernet dans `ServiceSecret`, jamais renvoyé), date d'expiration du secret (rappel à 30 jours), options : canaux, création de canaux, répercussion des modifications. « Vérifier la connexion » obtient un jeton d'application sans permission (valide annuaire + identifiant + secret).

### Application Microsoft Entra à créer par le client
1. Inscription d'application, comptes de cet annuaire uniquement.
2. URI de redirection (Web) : `https://<votre-domaine>/api/v1/teams/oauth/callback`.
3. Secret client (noter sa date d'expiration).
4. Permissions **déléguées** (moindre privilège) :
   - toujours : `User.Read`, `Chat.Create`, `ChatMessage.Send`, `Chat.Read`, `offline_access` ;
   - canaux : `Team.ReadBasic.All`, `Channel.ReadBasic.All`, `ChannelMessage.Send`, `ChannelMessage.Read.All` (consentement administrateur) ;
   - création de canaux : `Channel.Create` ; répercussion des modifications : `ChatMessage.ReadWrite`.
   Microsoft n'autorise l'envoi de messages qu'au nom d'un utilisateur : aucune permission d'application n'est utilisée.

## Compte de chaque utilisateur
Page Collaboration → « Relier mon compte Teams » : OAuth 2.0 code + PKCE, état en session (15 min, usage unique). Jetons d'accès et de renouvellement chiffrés au repos ; renouvelés automatiquement 5 minutes avant expiration ; consentement retiré → compte marqué « à reconnecter ». Les permissions manquantes sont affichées.

## Création côté Teams
- Conversation individuelle (2 personnes) ou de groupe (≥ 3) : les membres sont désignés par leur compte relié, sinon par leur e-mail.
- Canal : publication dans un canal **existant** (fil dédié) ; la création d'un canal est une opération distincte (droit « Collaboration · Valider »).
- Message initial structuré : sujet, projet, action, auteur, premier message, lien « Ouvrir dans PCT ».

## Synchronisation Teams → PCT
- **Notifications Microsoft Graph** (si `PUBLIC_BASE_URL` est en https) : abonnement par discussion (`/chats/{id}/messages` ou `/teams/{t}/channels/{c}/messages`, sans données dans la notification), 4 200 min (maximum Microsoft 4 320), `clientState` aléatoire dont seule l'empreinte est stockée, comparaison à temps constant, poignée de main `validationToken`, notifications de cycle de vie (`reauthorizationRequired`, `subscriptionRemoved`, `missed`).
- **Rejeu et doublons** : chaque notification est enregistrée (empreinte unique, purge à 3 jours) ; chaque message Teams est unique par discussion (contrainte en base).
- **Boucles** : un message publié depuis PCT est reconnu à son retour (identifiant, ou texte d'un envoi en attente) ; un état Teams plus ancien que l'état connu est ignoré.
- **Secours** : relecture périodique (`sync_teams`, appelée par la tâche planifiée) et bouton « Synchroniser ».

## API
`/api/v1/discussions`, `/discussions/{id}`, `/discussions/{id}/messages`, `/discussions/{id}/documents`, `/discussions/{id}/synchronize`, `/messages/{id}` (PATCH, DELETE, GET historique), `/messages/{id}/retry`, `/teams/connection-status`, `/teams/oauth/start`, `/teams/oauth/callback`, `/teams/unlink`, `/teams/joined-teams`, `/teams/teams/{id}/channels` (GET, POST), `/teams/webhook`, `/teams/lifecycle`, `/admin/teams`, `/admin/teams/check`, `/me/notification-preferences`.

## Tests
Microsoft Graph est remplacé par un faux (`collaboration/tests.py`, `FakeGraph`) : aucun appel réseau. Couverts : création de conversation et de canal, message structuré, publication, erreurs Graph, renouvellement et retrait du jeton, OAuth (état, PKCE, rejeu), synchronisation, déduplication, boucles, webhook authentifié et rejeu, cycle de vie, isolation, Pilote, droits, secrets.
