"""Assistants disponibles en appel, modèles de documents et vocabulaire de l'entretien (moteur local)."""

# Assistants invocables en appel. Les codes rejoignent ai_orchestrator.ROSTER (même licence, même journal).
CALL_ROLES = {
    "maestro": {"domain": "orchestration", "doc": "minutes"},
    "nova": {"domain": "fonctionnel", "doc": "sfd"},
    "altair": {"domain": "architecture", "doc": "std"},
    "orion": {"domain": "technique", "doc": "std"},
    "vega": {"domain": "qualite", "doc": "test"},
    "atlas": {"domain": "planning", "doc": "planning"},
    "mercure": {"domain": "budget", "doc": None},
    "lyra": {"domain": "client", "doc": None},
}

# Mots-clés de routage (Maestro) : domaine -> mots.
DOMAINS = {
    "architecture": ["architecture", "archi", "hébergement", "hebergement", "cloud", "azure", "aws", "serveur", "microservice",
                     "base de données", "base de donnees", "api", "kubernetes", "infrastructure", "scalab", "haute disponibilité"],
    "technique": ["développement", "developpement", "code", "framework", "bug", "déploiement", "deploiement", "ci/cd", "technique"],
    "qualite": ["recette", "test", "qualité", "qualite", "anomalie", "pv de recette", "non-régression"],
    "planning": ["planning", "jalon", "délai", "delai", "échéance", "echeance", "date de livraison", "sprint", "retard"],
    "budget": ["budget", "coût", "cout", "prix", "chiffrage", "jours-homme", "tjm", "devis", "facturation"],
    "client": ["contrat", "satisfaction client", "relation client", "avenant"],
    "fonctionnel": ["besoin", "fonctionnel", "règle de gestion", "regle de gestion", "parcours", "écran", "ecran", "user story", "exigence"],
}
DOMAIN_OWNER = {"architecture": "altair", "technique": "orion", "qualite": "vega", "planning": "atlas", "budget": "mercure",
                "client": "lyra", "fonctionnel": "nova"}

DOC_TYPE_LABEL = {"sfd": "SFD", "std": "HLD", "test": "Stratégie de recette", "planning": "Planning", "minutes": "Compte rendu"}

TEMPLATES = {
    "sfd": {
        "title": "Spécifications fonctionnelles",
        "sections": [
            ("contexte", "Contexte et enjeux", "Pour commencer, quel est le contexte du projet et le problème que vous voulez résoudre ?"),
            ("perimetre", "Périmètre", "Qu'est-ce qui est dans le périmètre de cette première version, et qu'est-ce qui en est exclu ?"),
            ("acteurs", "Acteurs et profils", "Qui utilisera la solution ? Citez les profils et ce que chacun doit pouvoir faire."),
            ("processus", "Processus métier", "Décrivez-moi le parcours principal, étape par étape, du point de vue de l'utilisateur."),
            ("regles", "Règles de gestion", "Quelles règles métier faut-il respecter ? Par exemple des calculs, des conditions ou des délais."),
            ("exigences", "Exigences fonctionnelles", "Quelles fonctionnalités sont indispensables ? Je les numérote au fur et à mesure."),
            ("ecrans", "Écrans et ergonomie", "Quels écrans sont prioritaires ? Avez-vous des maquettes ou un existant à reprendre ?"),
            ("donnees", "Données", "Quelles données sont manipulées, d'où viennent-elles, et faut-il reprendre l'existant ?"),
            ("nfr", "Exigences non fonctionnelles", "Côté volumétrie, performance, sécurité et disponibilité, quelles sont vos attentes chiffrées ?"),
            ("acceptation", "Critères d'acceptation", "Comment validerez-vous en recette que c'est conforme ?"),
            ("questions", "Questions ouvertes", None),
        ],
    },
    "std": {
        "title": "Dossier d'architecture (HLD)",
        "sections": [
            ("contexte", "Contexte et enjeux techniques", "Quel est le contexte technique : système existant, contraintes de l'entreprise, échéance ?"),
            ("nfr", "Exigences non fonctionnelles", "Quelle volumétrie, quels pics de charge et quelle disponibilité attendez-vous ?"),
            ("cible", "Architecture cible", "Comment voyez-vous l'architecture cible ? Je vous propose aussi des options."),
            ("integrations", "Intégrations et flux", "Avec quels systèmes la solution doit-elle échanger, et dans quel sens ?"),
            ("technos", "Choix technologiques", "Avez-vous des technologies imposées ou préférées (langage, base de données, cloud) ?"),
            ("ressources", "Ressources et dimensionnement", "Quelle équipe et quels environnements sont prévus (dev, recette, production) ?"),
            ("securite", "Sécurité et conformité", "Quelles exigences de sécurité : authentification, données personnelles, hébergement en France ?"),
            ("deploiement", "Déploiement et environnements", "Comment souhaitez-vous déployer : automatisation, fréquence de mise en production ?"),
            ("risques", "Risques techniques", "Quels risques techniques voyez-vous déjà ?"),
            ("recommandations", "Recommandations IA", None),
            ("decisions", "Décisions (ADR)", None),
            ("questions", "Questions ouvertes", None),
        ],
    },
}

# Cartes de choix proposées par l'architecte quand l'entretien atteint une section.
ARCHI_CHOICES = {
    "cible": ("Quel style d'architecture retenez-vous ?",
              [("Monolithe modulaire", "Simple à livrer et à exploiter ; découpage propre en modules", True),
               ("Microservices", "Mise à l'échelle fine, mais exploitation plus lourde", False),
               ("Serverless", "Coût à l'usage, adapté aux charges irrégulières", False)]),
    "technos": ("Quelle base de données principale ?",
                [("PostgreSQL", "Robuste, open source, déjà utilisée par Project Control Tower", True),
                 ("SQL Server", "Pertinent si l'écosystème Microsoft est imposé", False),
                 ("MongoDB", "Pour des données documentaires peu structurées", False)]),
    "deploiement": ("Où héberger la solution ?",
                    [("Azure (région France)", "Intégration Entra ID et Teams, données en France", True),
                     ("AWS (Paris)", "Large catalogue de services managés", False),
                     ("Sur site", "Maîtrise totale, mais exploitation à votre charge", False)]),
}

# Recommandations techniques déclenchées par des mots de la conversation.
ARCHI_HINTS = [
    (["pic", "charge", "saisonn", "black friday", "montée en charge"], "Prévoir une mise à l'échelle automatique et un test de charge avant la mise en production."),
    (["donnée personnelle", "donnees personnelles", "données personnelles", "rgpd", "santé", "sante"], "Chiffrer les données au repos et en transit, tenir le registre RGPD, limiter la durée de conservation."),
    (["sso", "entra", "azure ad", "active directory", "authentification"], "S'appuyer sur OpenID Connect avec l'annuaire de l'entreprise (SSO) plutôt que des comptes locaux."),
    (["temps réel", "temps reel", "notification", "websocket"], "Utiliser un canal temps réel (WebSocket) découplé par une file de messages."),
    (["excel", "export", "rapport", "reporting"], "Générer les exports en tâche de fond pour ne pas bloquer l'interface."),
    (["mobile", "smartphone", "tablette"], "Concevoir l'interface en responsive d'abord ; l'application native n'est utile qu'en cas d'usage hors ligne."),
    (["legacy", "existant", "migration", "reprise"], "Isoler l'existant derrière une API (anti-corruption layer) et migrer par lots."),
]

# Termes non mesurables (formes masculines et féminines) et suggestions de reformulation.
VAGUE_TERMS = {
    "rapide": ["Moins de 2 s pour 95 % des écrans", "Moins de 1 s pour les écrans de saisie"],
    "rapidement": ["Traitement en moins de 24 h ouvrées", "Réponse en moins de 2 s"],
    "performant": ["Moins de 2 s pour 95 % des écrans", "500 utilisateurs simultanés sans dégradation"],
    "performante": ["Moins de 2 s pour 95 % des écrans", "500 utilisateurs simultanés sans dégradation"],
    "simple": ["Tâche principale en 3 clics maximum", "Prise en main sans formation en 15 minutes"],
    "facile": ["Tâche principale en 3 clics maximum", "Prise en main sans formation en 15 minutes"],
    "intuitif": ["Prise en main sans formation en 15 minutes", "90 % de réussite au test utilisateur"],
    "intuitive": ["Prise en main sans formation en 15 minutes", "90 % de réussite au test utilisateur"],
    "convivial": ["Note de satisfaction d'au moins 4/5 en recette", "Conforme à la charte et au RGAA niveau AA"],
    "conviviale": ["Note de satisfaction d'au moins 4/5 en recette", "Conforme à la charte et au RGAA niveau AA"],
    "sécurisé": ["Authentification SSO et chiffrement TLS 1.2+", "Conforme à l'hygiène informatique de l'ANSSI"],
    "sécurisée": ["Authentification SSO et chiffrement TLS 1.2+", "Conforme à l'hygiène informatique de l'ANSSI"],
    "disponible": ["Disponibilité de 99,5 % en heures ouvrées", "Disponibilité de 99,9 % 24 h/24"],
    "etc": [],
    "à définir": [],
}

DOMAIN_LABEL = {"architecture": "l'architecture", "technique": "la technique", "qualite": "la recette", "planning": "le planning",
                "budget": "le budget", "client": "la relation client", "fonctionnel": "le fonctionnel"}
