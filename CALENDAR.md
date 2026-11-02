# Calendrier (1.4.0)

## Principe
Le calendrier ne double pas les actions : une action datée **a** un événement (`planning.CalendarEvent.action`, une seule planification par action). Dates, statut, priorité, phase et responsable modifiés dans le calendrier sont recopiés sur l'action, qui reste l'objet métier. Un événement sans action est un jalon, une réunion ou une tâche de planning.

- Dates en UTC (`start`, `end` exclusive) + fuseau d'origine (`timezone`, Europe/Paris par défaut). Journée entière : de minuit à minuit dans ce fuseau. L'API accepte `AAAA-MM-JJ` (journée, fin **incluse**) ou un instant ISO 8601 (avec décalage ou `Z`; sans décalage : fuseau de l'événement).
- Affectations multiples (`CalendarAssignment`) : un seul responsable (`owner`), contributeurs, relecteurs ; charge estimée et réalisée en heures.
- Dépendances FS/SS/FF/SF (`CalendarDependency`), refus des cycles.
- Rappels (`CalendarReminder`) : par défaut la veille de l'échéance pour le responsable, la veille d'un jalon pour tous ; rappels personnels sur PCT, e-mail ou Teams.
- Les actions datées existantes sont planifiées par la migration `planning/0002` (et par `load_demo`).

## Vues
Mois, Semaine, Jour, « Mon planning » : FullCalendar 6.1.19 (paquets **MIT** uniquement : core, react, daygrid, timegrid, interaction, list).
Collaborateurs, Équipes, Chronologie, Gantt, Portefeuille : développées dans PCT (le module « resource timeline » de FullCalendar est commercial). Glisser-déposer et redimensionnement au pointeur et au clavier (flèches ; Maj + flèches pour la durée). Filtres serveur : projet, collaborateur, équipe, statut, priorité, type, retard ; recherche ; zoom 2 semaines / 6 semaines / trimestre.

## Conflits
Calculés à l'enregistrement, **avant** toute écriture (transaction annulée) : double affectation, surcharge (charge > capacité journalière : `PersonCapacity` ou réglage `time.hpd`, 8 h par défaut), action sans responsable, dépendance non respectée, dépassement de la fin du projet, élément déjà en retard. Réponse `409 CALENDAR_CONFLICTS` avec, pour chaque conflit : explication et proposition (déplacer, allonger, désigner). L'utilisateur applique la proposition, enregistre malgré tout (`confirm: true`) ou annule. **Rien n'est jamais déplacé automatiquement.**
Un événement d'un projet que l'utilisateur ne voit pas compte dans la charge mais n'est jamais nommé (« un autre engagement »).

## Droits
Matrice, module « planning » : Voir (lecture), Créer, Modifier, Supprimer — appliqués sur les projets modifiables par l'utilisateur. Une personne affectée peut toujours mettre à jour statut, avancement et son temps réel. Couleurs : droit « Paramétrage · Modifier ». Le Pilote n'a aucun accès.

## Tableau de bord
`GET /api/v1/calendar/dashboard` : planifiés, terminés, en cours, bloqués, en retard, à venir, avancement moyen, respect des délais, charge par collaborateur et équipe, retards par projet, jalons ; conflits de la période (appliquer / ignorer).

## Abonnement ICS
`POST /api/v1/calendar/feed-token` donne un lien personnel (affiché une fois, empreinte seule stockée, révocable) lisible par Outlook, Google Agenda ou Apple Calendrier. La synchronisation bidirectionnelle est préparée (`ExternalCalendarLink`, `ExternalEventMapping` : etag, empreinte, unicité) mais aucun fournisseur n'est encore actif.

## Tâches planifiées
`process_calendar` (rappels échus, retards signalés une fois) — appelée par `/api/v1/cron/maintenance`. Les rappels échus sont aussi traités à la consultation du calendrier.
