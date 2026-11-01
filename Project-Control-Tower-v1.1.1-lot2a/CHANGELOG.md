# Changelog

Format : une entrée par lot livré, la plus récente en haut.

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
