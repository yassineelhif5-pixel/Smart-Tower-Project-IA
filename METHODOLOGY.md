# Pilotage méthodologique — Cycle en V et Scrum (1.5.0)

Écran **Pilotage** (droit « Méthodologie · Voir »). Les onglets dépendent de la méthodologie du projet. Tout repose sur l'existant : projets, actions, utilisateurs, documents, calendrier, notifications et connecteur Teams. Rien n'est validé, affecté, sélectionné ou modifié sans action explicite d'un utilisateur.

## Méthodologies
| Méthodologie | Fonctionnalités |
| --- | --- |
| Cycle en V | phases, semaines (Weekly Goals), capacité, rétrospectives |
| Scrum | backlog, sprints et cérémonies, capacité, rétrospectives |
| Agile hybride | phases, semaines, Scrum, capacité, rétrospectives |
| Personnalisée | au choix |

Changement de méthodologie : analyse d'impact (sprints ouverts, semaines non clôturées, phases, rétrospectives), puis confirmation explicite, droit « Méthodologie · Valider ». Aucune donnée n'est supprimée : les fonctions désactivées sont masquées. Historique conservé.
Reprise automatique des données existantes (migration `methodology/0002`) : champ méthode, planning macro (phases), équipe (`staff`, `PersonCapacity`), sprints et objectifs (`agile`), user stories et rétrospectives déjà saisies.

## Capacité
Par collaborateur et par jour travaillé (jours travaillés par semaine, période d'affectation) :
- théorique affectée = heures par jour × taux d'affectation ;
- jour d'absence complète (congé, absence, jour férié, indisponibilité sans heures) : 0 ;
- sinon : − indisponibilités partielles, − part quotidienne des réunions récurrentes, jamais sous 0.
Aucune indisponibilité n'est déduite deux fois (pas de réunion un jour de congé, absences superposées comptées une fois). Capacité productive = disponible × ratio productif du projet (30 à 100 %).
Exemple du cahier : 7 h × 5 j × 80 % = 28 h − 4 h de réunions − 2 h d'indisponibilité = **22 h** (test automatisé).
Charge planifiée : affectations du calendrier (charge estimée répartie sur les jours ouvrés) ; consommée : temps saisi ; autres projets : affichés à titre d'information. Surcharge : planifié > disponible ; sous-utilisation : < 60 %.
Disponibilités : chacun déclare les siennes ; celles d'un autre : « Capacité · Modifier » sur un projet commun ; jours fériés (toute l'entreprise) : « Capacité · Valider ».

## Cycle en V
- **Phases** configurables (douze proposées) : dates, fin prévisionnelle, responsable, statut, avancement, livrables, critères de validation, risques, dépendances. Jalons : événements du calendrier.
- **Semaine** : assistant en 10 étapes (reliquat, reports, disponibilités, capacité, propositions dans la limite de la capacité, affectations via le calendrier, charge, conflits, Weekly Goals, validation). Validation : chef de projet ou droit « Valider » ; surcharge → avertissement, confirmation explicite ; instantané de capacité enregistré.
- **Weekly Goals** : plusieurs par semaine, sur une ou plusieurs phases, actions liées, livrables, critères de réussite, risques.
- **Suivi** : prévu, terminé, en cours, bloqué, reporté, charge prévue et consommée, réalisation ; statut global non démarré / en cours / atteint / partiellement atteint / non atteint.
- **Bilan** automatique à la clôture : prévu vs obtenu, écarts (avec causes de blocage), risques, actions correctives.
- **Réunion hebdomadaire** : ordre du jour, participants, objectifs, avancement, problèmes, décisions ; ses actions deviennent des actions PCT ; événement dans le calendrier ; compte rendu généré.

## Scrum
- **Rôles** Product Owner, Scrum Master, Developers (plusieurs personnes par rôle), indépendants des droits PCT.
- **Product Backlog** : Epics, Features, User Stories, Tasks, Bugs, Spikes ; story points, estimation, dépendances, pièces jointes, historique ; tri, filtres, recherche, regroupement par Epic ; priorisation par glisser-déposer réservée au Product Owner (ou droit « Valider »).
- **Sprints** de 1 à 4 semaines ; statuts à préparer, planifié, en cours, terminé, annulé.
- **Sprint Planning** en 9 étapes : backlog priorisé, disponibilités, capacité, vélocité (moyenne des 3 derniers sprints), propositions, sélection, Sprint Goal, dépendances, points et charge. Dépassement de la vélocité (+20 %) ou de la capacité, dépendances non terminées → vérification explicite. Démarrage : Sprint Goal + validation du Product Owner + engagement de l'équipe ; toute modification du Sprint Backlog redemande ces validations.
- **Sprint Goal** : objectif, valeur, résultats, critères, risques, responsable, statut et progression propres — jamais déduits du % de tâches. Visible dans le board, le tableau de bord, le calendrier et le suivi.
- **Daily Scrum** : progrès, plan, obstacles (facultatif) ; obstacles suivis (action, responsable, échéance, statut) ; notes d'adaptation de l'équipe.
- **Sprint Board** : colonnes configurables (une colonne utilisée par un sprint ouvert ne peut pas être retirée), glisser-déposer, affectation, blocages, reste à faire, historique.
- **Suivi** : jours écoulés et restants, points prévus/terminés/restants, capacité initiale/consommée, charge restante, vélocité, blocages, burndown, burnup (scope réel : ajouts et retraits datés), répartition par personne.
- **Sprint Review** : incrément, démonstrations, retours, décisions, évolutions du backlog ; compte rendu généré.
- **Clôture** : statut du Sprint Goal saisi explicitement ; éléments non terminés renvoyés au backlog ou au sprint suivant ; rétrospective programmée.

## Rétrospectives
Création à la clôture d'un sprint, ou automatique pour le Cycle en V selon la fréquence (hebdomadaire, mensuelle, fin de phase, fin de jalon, fin de projet), idempotente. Événement dans le calendrier, participants invités, Scrum Master/animateur prévenu, rappels (48 h, 24 h, jour même — configurables par tenant et par projet), rappel si le compte rendu n'est pas finalisé.
Formats Start/Stop/Continue, Mad/Sad/Glad, What went well/What could improve, 4Ls, libre. Contributions anonymes seulement si la politique du tenant **et** la rétrospective l'autorisent : l'auteur n'est alors pas enregistré.
Chaque décision devient une **action PCT** (type « Amélioration ») : responsable, échéance, priorité, statut, indicateur, sprint ou période cible ; terminée dans PCT → réalisée. Les actions ouvertes réapparaissent dans la rétrospective suivante ; taux de réalisation mesuré. Clôture refusée sans compte rendu ni responsables/échéances, sauf clôture forcée (droit « Valider », tracée).

## Calendrier et notifications
Événements créés : réunion hebdomadaire, Sprint Planning, sprint (titre = Sprint Goal), Daily Scrum (option), Sprint Review, rétrospectives ; jalons et échéances déjà présents.
Rappels (`MethodologyReminder`) : début de semaine, préparation de la semaine, Sprint Planning, Daily, Sprint Review, rétrospective, compte rendu, clôture du sprint, action d'amélioration en retard. Clé d'unicité (jamais deux fois), annulation des rappels devenus sans objet, 3 essais avec délai croissant et journalisation des erreurs. Envoi par `notify` : règles du tenant, préférences de chacun, canaux PCT, e-mail, Teams.
Tâche planifiée : `process_methodology` (appelée par `/api/v1/cron/maintenance`).

## Assistance
« Propositions » (Weekly Goals, priorisation, retards, capacité, risques, Sprint Goal, blocages, résumé de sprint, synthèse et récurrences des rétrospectives) calculées par des **règles transparentes** sur les données du projet. Aucune IA générative n'est branchée (la plateforme n'a pas encore de Skill IA ni de quotas de jetons) ; l'interface est prête à recevoir un moteur IA plus tard, avec la même règle : jamais d'application automatique.

## Droits (matrice)
| Module | Voir | Créer / Modifier | Valider |
| --- | --- | --- | --- |
| Capacité | voir la capacité | disponibilités, affectations | jours fériés |
| Méthodologie | voir | planifier, Weekly Goals, Sprint Goals, backlog, sprints, cérémonies, rétrospectives, actions d'amélioration | valider la semaine, démarrer/clôturer un sprint, changer de méthodologie, clôture forcée |
Écritures : en plus, modification du projet ou appartenance à l'équipe. Portail client et Pilote : aucun accès.

## API (extrait)
`/api/v1/methodology/projects`, `/projects/{id}` (GET, PUT), `/impact`, `/assist`, `/capacity`, `/allocations`, `/availabilities`, `/phases`, `/weeks/{lundi}` (+ `/goals`, `/assign`, `/validate`, `/close`, `/meeting`), `/goals/{id}`, `/backlog`, `/backlog/reorder`, `/sprints`, `/scrum-dashboard`, `/sprints/{id}` (+ `/planning`, `/select`, `/goal`, `/validate`, `/start`, `/close`, `/review`, `/daily`), `/sprint-items/{id}`, `/impediments/{id}`, `/retros`, `/retros/{id}` (+ `/feedback`, `/improvements`, `/close`), `/feedback/{id}/vote`, `/improvements/{id}`, `/reports`, `/policy`.

## Limites
- Interface en français uniquement (pas encore de fichiers de traduction).
- Rappels traités par la tâche planifiée : sur l'offre gratuite de Vercel, une exécution par jour ; un planificateur plus fréquent est recommandé pour les rappels du Daily.
