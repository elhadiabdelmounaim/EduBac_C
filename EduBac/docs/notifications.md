# Notifications EduBac — exploitation

## Principes

- **Regroupement** : tant qu'une notification n'est pas lue, les événements du même
  groupe la mettent à jour au lieu d'en créer une nouvelle (ex. « 12/30 élèves ont
  terminé le quiz, moyenne 64 % » ; une notification par conversation privée).
  Ouvrir la conversation marque sa notification comme lue.
- **Préférences** (`/notifications/preferences/`) : pour chaque type,
  « dans EduBac » (badge) et e-mail (immédiat, résumé quotidien, jamais).
  Le catalogue des types et les valeurs par défaut sont dans
  `notifications/catalog.py`.
- Les élèves n'ont pas d'adresse e-mail : leurs notifications restent dans EduBac.
- **Historique complet** : `/notifications/` (filtres par type et non lues).

## Valeurs par défaut (professeur / administration)

| Type | E-mail |
|---|---|
| Signalements, inscriptions en attente | Immédiat |
| Résultats de quiz, quiz non faits, messagerie, vie de la classe | Résumé quotidien |

## Tâches à planifier (cron)

```cron
# Rappels élèves (48 h avant) et alertes « quiz non fait » aux professeurs
0 * * * *   cd /chemin/EduBac && python manage.py send_quiz_reminders
# Résumé quotidien par e-mail
0 18 * * *  cd /chemin/EduBac && python manage.py send_notification_digest
```

`send_notification_digest --dry-run` affiche ce qui serait envoyé.
Sans ces tâches, les rappels, les alertes et les résumés ne partent pas
(les notifications dans EduBac, elles, fonctionnent).
