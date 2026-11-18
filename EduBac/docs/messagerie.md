# Messagerie EduBac — exploitation

Trois messageries partagent le même socle (pièces jointes, édition, suppression,
signalement, synchronisation) :

| Type | Modèles | API de lecture |
|---|---|---|
| Salon de classe | `ClassChatRoom`, `ChatMessage` | `/chat/api/classe/<id>/messages/` |
| Consultation élève ↔ professeur | `PrivateConversation`, `PrivateMessage` | `/chat/api/consultations/<id>/messages/` |
| Message individuel (élève ↔ élève, élève ↔ administration) | `DirectConversation`, `DirectMessage` | `/chat/api/direct/<id>/messages/` |

## Règles de modération

- **Messages entre élèves** : désactivés par défaut. Le professeur les autorise
  classe par classe (réglages du salon). Un élève peut bloquer un camarade.
- **Professeur de la classe / administration** : suppression de tout message du
  salon, mode annonces (seul le professeur écrit), sourdine d'un élève
  (15 min à 7 jours), heures de silence (aussi appliquées aux messages privés
  des élèves de la classe, plage pouvant passer minuit).
- **Auteur** : modification pendant 5 minutes, suppression à tout moment.
  Les suppressions sont « douces » : le contenu reste en base pour l'audit,
  mais n'est plus jamais envoyé au navigateur.
- **Signalements** (`/chat/moderation/`) : le message et les 5 précédents sont
  figés au moment du signalement. Ils vont au professeur de la classe, sauf
  s'il est lui-même visé, et à l'administration. Les signalements de
  consultation vont uniquement à l'administration.

## Temps réel

- Sans `REDIS_URL` : couche Channels en mémoire (un seul processus). Les pages
  basculent automatiquement sur l'interrogation toutes les 3 s si le WebSocket
  n'est pas disponible (serveur WSGI, PythonAnywhere…).
- Avec `REDIS_URL=redis://hôte:6379/0` et un serveur ASGI (ex. `daphne
  config.asgi:application`) : WebSocket partagés entre processus, interrogation
  de secours ramenée à 30 s, cache partagé pour les limites de débit.

## Mise en service

```bash
python manage.py migrate chat
# Anciennes pièces jointes du salon (MEDIA_ROOT/chat) → stockage privé.
python manage.py move_class_chat_attachments          # simulation
python manage.py move_class_chat_attachments --apply
```

Les anciennes pièces jointes restent servies (via la vue contrôlée) tant que le
déplacement n'est pas fait.

## Conservation des données

```bash
python manage.py purge_chat_data                      # simulation
python manage.py purge_chat_data --apply \
    --attachments-days 365 --deleted-days 30 --reports-days 365
```

À planifier (cron) une fois les durées validées avec l'établissement.

## Brouillon IA (consultations)

Le professeur peut demander un brouillon de réponse : l'IA reçoit la leçon ou la
question de quiz liée et les 10 derniers messages, et ne fait que remplir le
champ de saisie. Rien n'est envoyé sans relecture. Limite : 6 demandes par
minute et par professeur.
