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

## Notifications sur le téléphone (Web Push)

Chaque notification EduBac (message privé, consultation, quiz, annonce…) et
chaque message du salon de classe s'affichent sur le téléphone, même EduBac
fermé, dès que le téléphone est connecté à Internet. Une seule notification par
conversation : la suivante la remplace.

Mise en route (une seule fois, sur le serveur) :

```bash
python manage.py migrate                 # table notifications_pushsubscription
python manage.py generate_vapid_keys     # copier les 3 lignes dans .env
```

Ne changez plus ces clés ensuite : les appareils déjà abonnés ne recevraient plus rien.

Côté utilisateur : cloche ▸ « Activer », ou Notifications ▸ Préférences ▸
« Notifications sur ce téléphone ».

- Android (Chrome) : fonctionne depuis le navigateur ou l'application installée.
- iPhone (iOS 16.4 ou plus) : **uniquement** depuis EduBac installé sur l'écran
  d'accueil (Safari ▸ Partager ▸ Sur l'écran d'accueil), règle d'Apple.

Les envois partent après la réponse HTTP : l'expéditeur n'attend jamais.
Les préférences « Dans EduBac » s'appliquent aussi au téléphone (un type
décoché n'envoie rien). Les appareils désinstallés sont oubliés automatiquement.

### Diagnostic

```bash
python manage.py push_check                # clés, appareils enregistrés par utilisateur
python manage.py push_check --send omar    # notification de test, avec la réponse du service de push
```

Chaque utilisateur peut aussi appuyer sur « Envoyer un test » dans Préférences de notification
(visible une fois les notifications activées sur l'appareil).
