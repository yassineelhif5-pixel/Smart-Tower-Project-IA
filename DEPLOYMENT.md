# Déploiement sur Vercel (avec Supabase)

Mis à jour le 2026-11-01 (version 1.3.1).

## Architecture du déploiement

Un seul projet Vercel, un seul domaine (`https://<projet>.vercel.app`) :

| Chemin | Service Vercel | Contenu |
| --- | --- | --- |
| `/api/…` | `backend` (Python 3.12, Django détecté par `backend/manage.py`) | API Django, une Vercel Function |
| tout le reste | `frontend` (Vite) | Interface React construite (`npm run build`) |

Le même domaine est indispensable : la connexion repose sur un cookie de session et le jeton CSRF. La base reste sur Supabase (PostgreSQL), jointe uniquement par Django. Les fonctions tournent à Dublin (`dub1`), près de la base Supabase (`eu-west-1`).

Fichiers concernés : `vercel.json` (services, routage, région, tâche planifiée), `backend/.python-version`, `.vercelignore`, `backend/config/vercel.py`.

Les « Services » de Vercel sont en bêta, disponibles sur toutes les offres. Vérifié en local avec la CLI Vercel 65.9.0 (`vercel build`) : les deux services se construisent, Django 5.2 est détecté avec son point d'entrée `config/wsgi.py`.

## 1. Base Supabase

1. Supabase → votre projet → **Connect** → onglet **Connection string** → **Session pooler**. Copiez l'adresse : elle ressemble à `postgresql://postgres.<ref>:[YOUR-PASSWORD]@aws-…-eu-west-1.pooler.supabase.com:5432/postgres`.
   - Utilisez le **Session pooler** : la connexion directe (`db.<ref>.supabase.co`) n'est pas joignable depuis Vercel, et le mode « Transaction » ne convient pas à Django.
2. Remplacez `[YOUR-PASSWORD]` par le mot de passe de la base (Settings → Database → Reset database password si vous ne l'avez plus) et ajoutez `?sslmode=require` à la fin. C'est votre `DATABASE_URL`.

## 2. Initialiser la base (une seule fois, puis à chaque nouvelle version)

Depuis votre ordinateur, dans le dossier `backend` (Python 3.12 ou plus) :

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
# Créez backend\.env (jamais envoyé sur GitHub) avec DATABASE_URL, DJANGO_SECRET_KEY, FIELD_ENCRYPTION_KEY :
# les MÊMES valeurs que sur Vercel.
python manage.py migrate
python manage.py create_pilot pilote        # note le mot de passe provisoire affiché une fois
python manage.py load_demo                  # facultatif : données de démonstration (tenant Demo ESN)
```

`migrate` ferme automatiquement les tables Django à l'API publique de Supabase (RLS activée, droits de `anon` et `authenticated` retirés). Les anciennes tables du schéma SQL archivé ne sont pas touchées.

Ne lancez pas `create_default_admin` sur une base publique : il crée `admin` / `admin`.

## 3. Projet Vercel

1. vercel.com → **Add New… → Project** → importez le dépôt GitHub `Smart-Tower-Project-IA`.
2. Laissez **Root Directory** à la racine du dépôt (le `vercel.json` décrit les deux services). Ne réglez ni « Framework Preset », ni commande de build.
3. **Avant le premier déploiement**, dans **Environment Variables** (cocher Production et Preview) :

| Variable | Valeur |
| --- | --- |
| `DATABASE_URL` | l'adresse du Session pooler (étape 1) |
| `DJANGO_SECRET_KEY` | longue chaîne aléatoire (générateur ci-dessous) |
| `FIELD_ENCRYPTION_KEY` | clé Fernet (générateur ci-dessous) — la même que dans votre `backend\.env` |
| `DB_CONN_MAX_AGE` | `0` (ménage le nombre de connexions du pooler) |
| `CRON_SECRET` | chaîne aléatoire (protège la maintenance planifiée) |
| `PUBLIC_BASE_URL` | `https://<projet>.vercel.app` (liens PCT dans Teams, retour OAuth Microsoft, notifications Graph) |

Ces variables sont lues dès la construction : sans elles, le déploiement échoue avec « Variable d'environnement manquante ».

Générer les clés sous Windows PowerShell (sans Python) :

```powershell
$b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b).Replace('+','-').Replace('/','_')
```

Lancez-la trois fois : une pour `FIELD_ENCRYPTION_KEY`, une pour `DJANGO_SECRET_KEY`, une pour `CRON_SECRET`.

4. **Deploy**. Une fois terminé, ouvrez `https://<projet>.vercel.app/api/v1/health` : la réponse doit être `{"status":"ok"}`. Puis l'adresse racine : écran de connexion, identifiant `pilote` et le mot de passe provisoire.

## Réglages automatiques sur Vercel

| Réglage | Sur Vercel | Pourquoi |
| --- | --- | --- |
| Hôtes autorisés | `*.vercel.app` ajouté | adresses de production et de prévisualisation |
| Redirection HTTPS par Django | désactivée | Vercel impose déjà le HTTPS |
| Adresse IP du journal d'audit | `X-Forwarded-For` pris en compte | Vercel réécrit cet en-tête avec l'adresse réelle |
| Préfixe `/api` | rétabli s'il manquait | garde-fou de routage |

Un domaine personnalisé s'ajoute dans `DJANGO_ALLOWED_HOSTS` (ex. `pct.mondomaine.fr`).

## Maintenance planifiée

`vercel.json` déclare une tâche quotidienne (3 h 17 UTC) qui appelle `/api/v1/cron/maintenance` : sessions inactives fermées, abonnements échus expirés, journaux purgés. La route exige `Authorization: Bearer <CRON_SECRET>` (Vercel l'envoie seul) et répond 404 si `CRON_SECRET` n'est pas défini. L'offre gratuite de Vercel n'autorise qu'une exécution par jour. Ce n'est pas bloquant : les sessions inactives et les abonnements échus sont aussi vérifiés à chaque connexion.

## Mettre à jour

1. Poussez sur GitHub : Vercel redéploie seul (`main` en production, les autres branches en prévisualisation).
2. Si la version contient des migrations : **sauvegarde Supabase**, puis `python manage.py migrate` depuis votre ordinateur. Les prévisualisations utilisent la même base que la production, sauf si vous leur donnez une autre `DATABASE_URL`.

## Limites

- Les prévisualisations partagent la base de production si `DATABASE_URL` est la même : pour des essais destructifs, créez un second projet Supabase.
- La documentation Swagger (`/api/v1/docs`) charge ses scripts depuis un CDN public.
- Durée maximale d'une requête : celle de l'offre Vercel (fonctions Fluid compute).
