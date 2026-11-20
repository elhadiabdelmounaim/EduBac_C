# Déploiement du tableau mathématique

## Constat sur PythonAnywhere

* Les applications web PythonAnywhere sont servies en **WSGI** : pas de
  WebSocket. L’offre ASGI existe mais reste expérimentale (accès sur demande,
  pas de correspondances statiques), et il n’y a ni Redis ni PostgreSQL dans
  l’offre standard.
* Un compte gratuit n’a qu’une application web : le service IA FastAPI ne peut
  pas y tourner à côté du site.

Le tableau a donc deux modes, **sans changement de code** :

| | Mode A — PythonAnywhere actuel | Mode B — serveur complet (VPS) |
|---|---|---|
| Serveur | WSGI | ASGI (Daphne) |
| Base | SQLite | PostgreSQL |
| Diffusion | interrogation HTTP (1 à 3 s) | WebSocket + Redis (instantané, curseurs) |
| Présence | toutes les 5 s | instantanée |
| IA | service FastAPI hébergé ailleurs (facultatif) | conteneur `ai` |
| Variable | `MATHBOARD_WEBSOCKET=0` (défaut) | `MATHBOARD_WEBSOCKET=1` |

Dans les deux modes, la base de données reste la seule source de vérité.

## Mode A — PythonAnywhere (production actuelle, rien ne casse)

```bash
cd ~/EduBac_C/EduBac
git pull
pip install -r requirements.txt          # ajoute djangorestframework et sympy
python manage.py backup_db
python manage.py migrate                 # tables du tableau mathématique (mathboard 0001 à 0003)
python manage.py collectstatic --noinput
```
Puis « Reload ».

**Tâche planifiée quotidienne** (onglet « Tasks » de PythonAnywhere) :
```bash
cd ~/EduBac_C/EduBac && python manage.py mathboard_cleanup
```
Elle allège le journal d’opérations, déplace en fichiers les images envoyées
hors ligne, supprime les fichiers d’images inutilisés et les présences
périmées (`--dry-run` pour voir sans rien changer).

**Assistant IA** : désactivé (aucun bouton). Pour le réactiver plus tard :
`MATHBOARD_AI_ENABLED=1` dans le `.env`, plus `MATHBOARD_AI_URL` et
`MATHBOARD_AI_TOKEN` (voir « Service IA seul » ci-dessous).

**Écriture → texte et formules** (bouton « Convertir », enseignants) :
désactivé par défaut. Pour l’activer :

```bash
pip install -r requirements-ecriture.txt      # paquet anthropic
```

puis dans le `.env` : `MATHBOARD_HANDWRITING_ENABLED=1` et
`ANTHROPIC_API_KEY=<clé>` (facultatif : `MATHBOARD_HANDWRITING_MODEL`, par
défaut `claude-opus-5-5`), et Reload. Chaque conversion est facturée par
Anthropic au compte de la clé. Compte gratuit PythonAnywhere : vérifier que
`api.anthropic.com` est accessible (liste des sites autorisés).

**Anciens tableaux** : chaque professeur peut convertir les siens (bouton dans
la liste de l’ancien tableau), ou tous d’un coup :
`python manage.py mathboard_convert_legacy --all`.

Note : les calculs SymPy s’exécutent dans un processus séparé limité à 8 s et
512 Mo ; le serveur reste disponible même sur une expression piège.

## Mode B — VPS avec Docker (temps réel complet)

Prérequis : un VPS (2 Go de RAM suffisent), un nom de domaine pointant vers lui,
Docker. Dans `.env` (jamais commité) :

```
DJANGO_SECRET_KEY=<long et aléatoire>
ALLOWED_HOSTS=votre-domaine.ma
CSRF_TRUSTED_ORIGINS=https://votre-domaine.ma
SITE_DOMAIN=votre-domaine.ma
POSTGRES_DB=edubac
POSTGRES_USER=edubac
POSTGRES_PASSWORD=<aléatoire>
AI_SERVICE_TOKEN=<aléatoire, partagé Django ↔ service IA>
AI_PROVIDERS=groq,openrouter            # ordre d’essai, repli automatique
GROQ_API_KEY=<clé>                       # lue seulement par le conteneur « ai »
OPENROUTER_API_KEY=<clé>
EMAIL_HOST_USER=…                        # exigés par config/settings_production.py
EMAIL_HOST_PASSWORD=…
WEBPUSH_VAPID_PUBLIC_KEY=…               # reprendre les valeurs actuelles
WEBPUSH_VAPID_PRIVATE_KEY=…
```
```bash
docker compose up -d --build
```
Services : `web` (Daphne), `redis`, `db` (PostgreSQL), `ai` (FastAPI), `caddy`
(HTTPS automatique, `/static/`, proxy HTTP et WebSocket).

### Migrer les données depuis PythonAnywhere
1. Sur PythonAnywhere : `python manage.py dumpdata --natural-foreign --natural-primary
   -e contenttypes -e auth.permission -o edubac.json` et copier `media/`.
2. Sur le VPS : `docker compose run --rm web python manage.py loaddata edubac.json`
   et copier `media/` dans le volume `media_data`.
3. Vérifier connexion, quiz, chat, tableaux, puis basculer le DNS.

## Service IA seul (pour le mode A)

Sur n’importe quel hôte acceptant un processus Python :
```bash
pip install -r ai_service/requirements.txt
AI_SERVICE_TOKEN=… AI_PROVIDERS=groq GROQ_API_KEY=… \
  uvicorn ai_service.app:app --host 0.0.0.0 --port 8100   # depuis le dossier EduBac/
```
Puis, dans le `.env` du site : `MATHBOARD_AI_URL=https://hote-ia` et
`MATHBOARD_AI_TOKEN=<même jeton>`. Les clés d’IA restent sur l’hôte du service.

## Vérifications après déploiement
* `/tableau-maths/` : créer un document, dessiner, insérer une formule et une figure.
* Deux navigateurs (professeur + élève) : la modification apparaît chez l’autre ;
  en mode B le statut indique « en direct » et les curseurs s’affichent.
* Couper le réseau, dessiner, rétablir : statut « Hors ligne — n en attente » puis « Enregistré ».
* Versions : créer, modifier, restaurer.
* Préparer sans partager : créer pour une classe avec « Préparer sans partager »,
  vérifier qu’un élève ne le voit pas, puis « Partager maintenant ».
* Travail à rendre : cocher « Travail à rendre » dans « Partager », l’élève
  fait sa copie et la rend, le professeur la corrige, l’élève voit la note.
* « Présenter » : l’élève suit la page et la zone du professeur.
* Notifications : l’élève est prévenu du partage et de la correction.
