# Changelog

Format : une entrée par lot livré, la plus récente en haut.

## [1.5.0] — 2026-11-01 — Pilotage Cycle en V et Scrum, capacité, rétrospectives

### Ajouté
- **Pilotage méthodologique** (`methodology`, voir `METHODOLOGY.md`) : méthodologie par projet (Cycle en V, Scrum, hybride, personnalisée) avec analyse d'impact et validation ; reprise des données existantes.
- **Capacité réelle** : affectations, heures, jours travaillés, réunions récurrentes, congés, absences, jours fériés, indisponibilités ; capacité théorique, disponible, productive, planifiée, consommée ; surcharges et sous-utilisation ; tableau de bord par semaine et par collaborateur.
- **Cycle en V** : phases configurables, assistant de préparation hebdomadaire, Weekly Goals, validation avec contrôle de surcharge, suivi, bilan automatique, réunion hebdomadaire.
- **Scrum** : Product Backlog (priorisation par le PO), sprints, Sprint Planning en 9 étapes, Sprint Goal suivi à part, double validation PO/équipe, Daily Scrum et obstacles, Sprint Board configurable, Sprint Review, clôture ; burndown, burnup, vélocité.
- **Rétrospectives** : 5 formats, contributions anonymes selon la politique du tenant, actions d'amélioration devenant des actions PCT, rétrospectives automatiques du Cycle en V.
- **Calendrier et rappels** : cérémonies dans le calendrier, rappels uniques avec nouvel essai, 8 nouveaux événements de notification ; commande `process_methodology`.
- Modules « Capacité » et « Méthodologie » dans la matrice des droits ; 14 écrans React ; propositions automatiques fondées sur des règles (aucune IA générative).
- 30 tests backend et 6 tests frontend ; parcours navigateur.

## [1.4.0] — 2026-11-01 — Calendrier intelligent, discussions et Microsoft Teams

### Ajouté
- **Calendrier** (`planning`, voir `CALENDAR.md`) : vues Mois, Semaine, Jour, Collaborateurs, Équipes, Portefeuille, Chronologie, Gantt, Mon planning et tableau de bord ; filtres, recherche, zoom ; glisser-déposer et redimensionnement (pointeur et clavier) ; affectations multiples avec charge estimée et réalisée ; dépendances ; fuseaux horaires ; couleurs par tenant.
- **Conflits expliqués avant enregistrement** (double affectation, surcharge, sans responsable, dépendance, fin de projet, retard) avec proposition ; jamais de modification automatique.
- **Rappels et notifications** : rappels par défaut et personnels (PCT, e-mail, Teams), retards signalés une fois, nouveaux événements de notification ; **préférences personnelles** (Mon accès) qui restreignent les règles de l'entreprise.
- **Abonnement ICS** personnel et révocable ; modèles prêts pour la synchronisation Outlook / Microsoft 365 / Google.
- **Discussions** (`collaboration`, voir `TEAMS_INTEGRATION.md`) sur projets et actions : interne, Teams ou les deux ; mentions, réponses, pièces jointes, modification et suppression de ses messages, historique, état de publication et renvoi ; page Collaboration.
- **Connecteur Microsoft Teams** par tenant (Microsoft Graph, permissions déléguées minimales, OAuth + PKCE, jetons chiffrés et renouvelés), conversations individuelles et de groupe, canaux (création distincte), webhooks authentifiés avec renouvellement, relecture de secours, déduplication, anti-boucle.
- Onglet Configuration « Connecteurs » ; module « Collaboration » dans la matrice des droits ; commandes `process_calendar` et `sync_teams` (tâche planifiée) ; réglage `PUBLIC_BASE_URL`.
- 55 tests backend (Graph simulé) et 14 tests frontend ; parcours navigateur complet.

### Modifié
- Migrations de reprise (réversibles, sans suppression) : actions datées planifiées, commentaires d'actions repris en discussions internes, droits « Collaboration » et règles de notification créés pour chaque tenant existant.
- Calendrier et Collaboration chargés à la demande (page d'accueil allégée).

## [1.3.1] — 2026-11-01 — Mise en ligne sur Vercel

### Ajouté
- `vercel.json` : un projet, deux services (frontend Vite, backend Django), `/api/…` vers Django sur le même domaine, région Dublin, tâche planifiée quotidienne. `backend/.python-version` (3.12), `.vercelignore`.
- Route `/api/v1/cron/maintenance` protégée par `CRON_SECRET` : sessions inactives, abonnements échus, purge des journaux.
- Verrouillage Supabase après chaque `migrate` : RLS activée et droits de `anon`/`authenticated` retirés sur toutes les tables Django (elles ne sont plus lisibles par l'API publique de Supabase).
- Réglages automatiques sur Vercel : `*.vercel.app` autorisé, redirection HTTPS laissée à Vercel, adresse IP réelle dans l'audit, préfixe `/api` garanti. `DB_CONN_MAX_AGE` configurable.
- `DEPLOYMENT.md` ; 4 tests (préfixe, maintenance planifiée, verrouillage Supabase).

## [1.3.0] — 2026-11-01 — SaaS multi-tenant, Pilote, offres et licences

### Ajouté
- **Multi-tenant** (`tenants`) : un tenant par entreprise ; colonne `tenant` sur toutes les tables métier, de configuration et de licences ; tenant déterminé côté serveur ; garde-fous à l'écriture ; commande `check_tenants` ; statuts actif, suspendu, désactivé, archivé.
- **Pilote (Super Admin Global)** : rôle sans tenant, créé en ligne de commande (`create_pilot`) ; console : tableau de bord, entreprises (création avec offre et premier administrateur), offres et versions, abonnements, stock de licences, demandes, journal de la plateforme, base de données.
- **RBAC dynamique** : profils Responsable de licences et Lecture seule ; droits d'administration délégables par rôle et par utilisateur (`accounts/capabilities.py`), privilèges du Pilote non délégables ; écran « Délégations ».
- **Offres et licences** (`licensing`) : offres versionnées, contrats, abonnements (essai, actif, suspendu, expiré, résilié), quotas d'utilisateurs et de fonctionnalités, licences nominatives (affecter, libérer, réaffecter, historisées) et concurrentes (réservation atomique, expiration d'inactivité, révocation) ; commande `expire_licenses`.
- **Demandes et approbations** : circuit complet (9 statuts), approbation partielle, exécution distincte de l'approbation, historique, notifications.
- **Interfaces** : console Pilote, onglets « Licences et demandes » et « Délégations » de l'administrateur, écran Licences des profils délégués, page « Mon accès ».
- **Audit** : adresse IP et résultat ; protection en base contre toute modification ; export CSV du journal de l'entreprise.
- Documentation : `MULTI_TENANT_ARCHITECTURE.md`, `TENANT_ISOLATION.md`, `LICENSING.md`, `API_DOCUMENTATION.md`, `SECURITY.md`.
- 52 tests backend (isolation, licences, concurrence, élévation de privilèges, audit) et 5 tests frontend.

### Modifié
- Administration (`/api/v1/admin/…`) limitée au tenant de l'administrateur ; un objet d'un autre tenant répond 404.
- Secrets, canaux, règles, réglages, jetons et journaux propres à chaque tenant.
- L'état de la base de données est un paramètre global : réservé au Pilote (l'onglet a quitté la Configuration des entreprises).
- `load_demo` rattache les données de démo au tenant Demo ESN ; `create_default_admin` crée l'administrateur de Demo ESN.

### Corrigé (trouvé pendant les tests)
- Le changement de mot de passe renouvelait l'identifiant de session et faisait perdre la licence : la licence suit désormais la session.
- L'expiration d'un abonnement constatée lors d'une connexion refusée était annulée : elle est désormais conservée.

### Conservé
- Toutes les données (rattachées à Demo ESN), routes, écrans et fonctions existants.

## [1.2.0] — 2026-11-01 — Lot 2b : schéma unique

### Ajouté
- **Toutes les tables métier de Supabase dans Django** (migration `projects/0002_metier_supabase`) : contrats clients, capacité des personnes, données internes et financières des projets, user stories, commentaires, objectifs, listes de tâches personnelles, saisies de temps, risques, incidents, demandes de changement et leurs montants, campagnes de test, anomalies, documents, réunions. Réglages métier partagés dans `configuration.AppSetting` (migration `configuration/0004`).
- **Règles de lecture** : `projects.access.visible(user, Modèle)` reprend une à une les politiques RLS de Supabase. Vérifié sur une copie locale : 280 contrôles, 0 écart (`supabase/verify_django_equivalence.py`).
- **Lecteur de `seed.sql`** (`projects/seed_sql.py`) : il s'arrête sur tout format inattendu pour ne perdre aucune valeur.
- `DATABASE.md` : correspondance complète des 25 tables Supabase vers Django.
- 10 tests (`backend/projects/test_schema.py`) : fidélité champ par champ des 1 907 lignes de démo, idempotence du chargement, conservation des données existantes à travers la migration, règles de lecture.

### Modifié
- `Client`, `Project` et `Action` reçoivent les colonnes de Supabase (25 colonnes facultatives, 3 relations). Aucun champ existant n'est modifié.
- `load_demo` charge désormais toutes les tables depuis `supabase/seed.sql` ; il reste idempotent et ne supprime jamais rien.
- `supabase/migrations/20261030220000_schema.sql` est marqué archivé (en-tête) ; son contenu n'a pas changé.

### Conservé
- Toutes les routes, les écrans et le périmètre par affectations (`ProjectAccess`).
- Aucune nouvelle route : les pages métier passeront par l'API au lot 4a.

## [1.1.1] — 2026-11-01 — Lot 2a : stabilisation

### Ajouté
- **API versionnée** : toutes les routes sont servies sous `/api/v1/`. Le frontend l'utilise désormais.
- **Documentation OpenAPI** (drf-spectacular) : `GET /api/v1/schema` et page Swagger `/api/v1/docs`, réservées aux administrateurs connectés en session (refusées aux jetons API).
- **Purge des journaux** : commande `python manage.py purge_logs` (option `--dry-run`), durées réglables par `API_LOG_RETENTION_DAYS` (90 j) et `AUDIT_LOG_RETENTION_DAYS` (365 j, minimum 30). Chaque purge est tracée dans le journal d'audit.
- **Rotation de la clé de chiffrement** : `FIELD_ENCRYPTION_KEY` accepte plusieurs clés séparées par des virgules, et la commande `python manage.py rotate_secrets` rechiffre les secrets avec la nouvelle clé (tracée dans l'audit).
- 11 tests de non-régression (`backend/configuration/test_stabilisation.py`).

### Modifié
- **Limite de connexion partagée** : le compteur de 10 tentatives par minute est stocké dans PostgreSQL (cache `pct_cache`, créé par la migration `configuration/0003`) au lieu de la mémoire de chaque processus. Il n'est plus remis à zéro au redémarrage et vaut pour tous les processus serveur.
- La liste des routes du module Configuration (onglet API) affiche les chemins `/api/v1/`.
- `README.md` : décision « Django seul propriétaire du schéma », nouvelles variables et commandes.

### Conservé
- L'ancien chemin `/api/` sans version reste servi à l'identique, pour les applications tierces déjà branchées.
- Toutes les fonctionnalités, données et routes existantes.

### Supprimé
- `.github/workflows/jekyll-docker.yml` : il construisait un site Jekyll inexistant à chaque envoi. La publication GitHub Pages (`static.yml`) est inchangée.
- `frontend/tsconfig.tsbuildinfo` : fichier de cache de compilation, désormais ignoré par Git.

## [1.1.0] — 2026-10-31

- Backend Django + DRF (connexion, module Configuration, périmètre projets et tâches), frontend React, schéma SQL Supabase, assistant de la démo respectant le profil.
