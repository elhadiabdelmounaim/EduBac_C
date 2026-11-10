# Déployer EduBac sur PythonAnywhere

> Guide historique. Le guide maintenu et vérifié est [PYTHONANYWHERE_DEPLOYMENT.md](./PYTHONANYWHERE_DEPLOYMENT.md). Utilisez-le pour les commandes actuelles.

Guide établi à partir de l’arborescence actuelle d’EduBac. Le compte PythonAnywhere n’étant pas encore identifié comme gratuit ou payant, les choix dépendant de l’offre sont indiqués séparément.

## 1. Architecture vérifiée

- Le dépôt contient le projet Django dans `EduBac/`; `manage.py`, `config/settings.py`, `config/urls.py`, `config/wsgi.py` et `config/asgi.py` sont dans ce dossier.
- La configuration par défaut utilise SQLite. Une configuration PostgreSQL par `DATABASE_URL` existe déjà; une configuration MySQL explicite est ajoutée dans `config.settings_production`. Lors de la validation de ce déploiement, l’environnement du workspace sélectionnait PostgreSQL quand `DATABASE_URL` était défini. Sa valeur n’a pas été consultée ni affichée : vérifiez le moteur avant de choisir une procédure de transfert.
- Les migrations présentes étaient appliquées dans la base locale et `makemigrations --check --dry-run` n’a détecté aucun changement de modèle. Aucune opération `DeleteModel`, `RemoveField` ou `RunSQL` n’a été trouvée dans les migrations actuelles.
- Les fichiers pédagogiques suivis par Git se trouvent sous `media/lessons/`. La base SQLite, les téléversements de chat, les résultats de classe et plusieurs autres fichiers du dossier `media/` sont ignorés par Git : un clonage du dépôt ne les transfère pas.
- Les fichiers de chat, les images de tableau blanc et les résultats de classe doivent rester soumis aux contrôles Django. **Ne créez pas de correspondance statique `/media/` vers tout `MEDIA_ROOT`.** Les pièces jointes de chat et les PDF attachés aux leçons sont servis par des vues Django; les documents de cours, images partagées et résultats ont leurs propres contrôles d’accès.
- Les statiques source sont dans `static/`; la collecte les copie vers `staticfiles/`.
- `channels` et `config.asgi` sont utilisés par le chat et le tableau blanc. La couche Channels actuelle est en mémoire.
- L’authentification opérationnelle du site est personnalisée. `django-allauth` n’est ni dans les dépendances ni dans `INSTALLED_APPS`; les adaptateurs présents ne rendent donc pas Google OAuth opérationnel.
- Les dépendances de production comprennent Django, Pillow, Groq, Channels, `openpyxl`, `pypdf`, Markdown et `pylatexenc`. Daphne et Playwright sont réservés au fichier `requirements-dev.txt`. Uvicorn et `mysqlclient` sont fournis comme dépendances optionnelles ci-dessous.

## 2. Choisir le mode d’hébergement

### Site WSGI classique

C’est le mode à utiliser dans l’onglet **Web** de PythonAnywhere pour les pages Django habituelles. Il prend en charge les requêtes HTTP, les formulaires, les quiz, l’import/export et les téléchargements.

Le chat dispose déjà d’une interrogation HTTP périodique, ce qui lui permet de continuer à actualiser les messages sans WebSocket, avec un délai plutôt qu’une diffusion instantanée. Le partage en lecture seule du tableau blanc a également une interrogation de secours. En revanche, la collaboration en direct sur le tableau blanc utilise WebSocket et ne fonctionnera pas sur un déploiement WSGI classique.

### WebSockets / ASGI

Le serveur WSGI classique de PythonAnywhere ne prend pas en charge les WebSockets. PythonAnywhere publie une option ASGI expérimentale accessible via son API/outil `pa`; il faut demander l’accès au programme bêta depuis le compte. La documentation signale notamment l’absence de correspondances statiques dans cette option et recommande Uvicorn plutôt que Daphne. Les conditions et tarifs de l’ASGI bêta peuvent évoluer.

Même avec l’accès bêta, EduBac n’est pas prêt à y basculer sans définir et tester séparément l’hébergement des fichiers statiques. Ne remplacez pas le mode WSGI par l’ASGI bêta avant d’avoir validé les statiques, les connexions WebSocket, les sessions et les téléchargements.

L’application utilise actuellement une couche Channels en mémoire : elle convient à un seul processus ASGI, mais ne synchronise pas plusieurs processus. Un déploiement multi-processus nécessiterait un backend de canaux partagé, par exemple Redis, si le service choisi le permet.

### Offre gratuite, MySQL et tâches planifiées

Les possibilités dépendent de la date de création et de la région du compte. À la date de rédaction, les nouveaux comptes gratuits ne disposent pas de MySQL ni de tâches planifiées; certains anciens comptes gratuits peuvent conserver des options antérieures. Vérifiez les fonctions réellement affichées dans votre compte avant de choisir la base ou l’automatisation. SQLite est le choix initial qui ne dépend pas d’un service MySQL.

## 3. Préparer le compte et le code

1. Créez un compte PythonAnywhere et ouvrez une console **Bash**.
2. Choisissez Python 3.12, compatible avec l’exigence Python du projet. Si cette version n’est pas proposée pour votre compte, ne choisissez pas une version inférieure sans vérifier d’abord la compatibilité de Django et des dépendances.
3. Clonez le dépôt dans le chemin utilisé par les exemples ci-dessous. Remplacez le marqueur par l’URL GitHub réelle :

```bash
git clone <URL_DU_DEPOT_GITHUB> "$HOME/EduBac"
cd "$HOME/EduBac/EduBac"
```

Créez l’environnement virtuel et installez les dépendances principales :

```bash
mkvirtualenv --python=python3.12 edubac-venv
workon edubac-venv
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Le chemin de l’environnement virtuel à renseigner dans l’onglet **Web** sera `~/.virtualenvs/edubac-venv`.

## 4. Variables d’environnement et secrets

Créez le fichier privé `.env` à partir du modèle, puis protégez-le :

```bash
cd "$HOME/EduBac/EduBac"
cp .env.example .env
chmod 600 .env
```

Éditez `.env` sur PythonAnywhere. Au minimum, renseignez :

```dotenv
DJANGO_SECRET_KEY=<clé-aléatoire-privée>
DEBUG=False
ALLOWED_HOSTS=<identifiant>.pythonanywhere.com
CSRF_TRUSTED_ORIGINS=https://<identifiant>.pythonanywhere.com
SITE_URL=https://<identifiant>.pythonanywhere.com
DATABASE_ENGINE=sqlite
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=0
```

Pour générer une clé, activez l’environnement virtuel et exécutez `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`. Copiez le résultat uniquement dans le `.env` privé. Ne le placez ni dans GitHub, ni dans `config/wsgi.py`, ni dans une capture d’écran partagée.

Le remplacement de l’ancienne clé codée dans les réglages invalide les sessions Django déjà signées avec celle-ci. Les utilisateurs devront se reconnecter; leurs comptes, quiz et résultats ne sont pas supprimés.

Pour un domaine personnalisé, ajoutez chaque nom exact à `ALLOWED_HOSTS` et chaque origine complète en HTTPS à `CSRF_TRUSTED_ORIGINS`, séparés par des virgules. La configuration de production refuse les hôtes génériques (`*`) et les valeurs de développement (`localhost`, `127.0.0.1`).

`SECURE_SSL_REDIRECT=True` suppose que le domaine a déjà HTTPS. Activez et vérifiez HTTPS avant d’ouvrir le site. Une fois le domaine et tous ses sous-domaines vérifiés, vous pouvez porter `SECURE_HSTS_SECONDS` à `31536000`; n’activez `SECURE_HSTS_INCLUDE_SUBDOMAINS` que si chaque sous-domaine concerné utilise HTTPS.

Avec `SECURE_HSTS_SECONDS=0`, `check --deploy` signale l’absence de HSTS. C’est volontaire tant que HTTPS et les sous-domaines ne sont pas confirmés. Après activation de HSTS, les avertissements sur `SECURE_HSTS_INCLUDE_SUBDOMAINS` et `SECURE_HSTS_PRELOAD` doivent être évalués pour votre domaine; ne les activez pas simplement pour faire disparaître les avertissements.

Les clés IA sont facultatives pour le fonctionnement du site, mais la génération IA exige une clé du fournisseur choisi (`GROQ_API_KEY` par défaut; alternatives dans `.env.example`). Les comptes PythonAnywhere gratuits peuvent limiter les connexions sortantes : vérifiez l’accès aux domaines des API utilisées avant d’activer cette fonction. Le modèle ne contient aucune clé.

Les courriels utilisent Gmail SMTP (`smtp.gmail.com`, port `587`, TLS). Configurez `EMAIL_HOST_USER` avec l’adresse Gmail du compte et `EMAIL_HOST_PASSWORD` avec son mot de passe d’application Google — jamais le mot de passe habituel du compte. Renseignez ces valeurs uniquement dans l’environnement privé, et non dans Git.

PythonAnywhere peut limiter les connexions sortantes SMTP selon l’offre et le compte. Depuis l’environnement PythonAnywhere, lancez `python manage.py check_email` pour vérifier la connexion et l’authentification sans envoyer de message. Après réussite, un administrateur peut envoyer un seul test avec `python manage.py check_email --send-test adresse-de-test@example.com`. Ne considérez pas la livraison comme vérifiée tant que ce test réel n’a pas été accepté par Gmail et reçu à l’adresse choisie.

## 5. Base de données et conservation des fichiers

### Si la base source est SQLite

La base locale `db.sqlite3` est ignorée par Git; elle n’arrivera donc pas avec `git clone`. Faites une sauvegarde et transférez la base existante vers PythonAnywhere par un moyen privé. Ne remplacez jamais une base déjà utilisée sur PythonAnywhere sans sauvegarde et vérification de son contenu.

La configuration par défaut utilise `"$HOME/EduBac/EduBac/db.sqlite3"`. Pour utiliser un autre emplacement, créez d’abord le dossier, puis fixez un chemin absolu dans `.env`, par exemple `SQLITE_PATH=/home/<identifiant>/data/edubac.sqlite3`. Transférez la base existante à cet emplacement avant les migrations.

Avant de transférer une base, vérifiez uniquement son moteur dans l’environnement source; cette commande n’affiche aucune URL ni aucun mot de passe :

```bash
python manage.py shell -c "from django.conf import settings; print(settings.DATABASES['default']['ENGINE'])"
```

Si le résultat est PostgreSQL, il n’existe pas de fichier SQLite à copier pour cette base. PythonAnywhere n’inclut pas PostgreSQL dans son offre standard : choisissez un PostgreSQL externe accessible depuis le compte, ou planifiez une conversion testée vers SQLite/MySQL. Pour une conversion Django par fixture, exportez depuis la source vers un emplacement privé hors du dépôt :

```bash
mkdir -p "$HOME/backups/edubac"
python manage.py dumpdata --natural-foreign --natural-primary \
  --exclude contenttypes --exclude auth.permission \
  --output "$HOME/backups/edubac/edubac-data.json"
```

Transférez ce fichier de manière privée. Sur PythonAnywhere, après les migrations de schéma et uniquement sur une base vide, chargez-le :

```bash
python manage.py loaddata "$HOME/backups/edubac/edubac-data.json"
```

Ne lancez pas `load_curriculum` avant cette importation. Testez d’abord l’export/import sur une base de préproduction; le fichier de fixture contient les données des comptes et doit être protégé comme une sauvegarde. Transférez séparément tous les médias. Ne lancez jamais `loaddata` sur une base déjà peuplée.

Sauvegardez la base et les fichiers avant toute mise à jour. Pour SQLite, utilisez la commande Django : elle crée une copie cohérente même si SQLite utilise WAL, dans `~/backups/edubac/`, hors du dépôt.

```bash
cd "$HOME/EduBac/EduBac"
python manage.py backup_db
mkdir -p "$HOME/backups/edubac"
if [ -d media ]; then
  tar -czf "$HOME/backups/edubac/media.$(date +%Y%m%d-%H%M%S).tar.gz" media
fi
```

Les médias ignorés par Git doivent aussi être transférés en conservant leurs sous-dossiers. Ne lancez pas `git clean`, ne supprimez pas `media/` et ne décompressez pas une archive par-dessus des fichiers existants sans comparer son contenu.

### Vérifier et appliquer les migrations

Après avoir transféré la base correspondant au code, activez l’environnement virtuel et inspectez le plan :

```bash
cd "$HOME/EduBac/EduBac"
workon edubac-venv
python manage.py showmigrations
python manage.py migrate --plan
```

Si le plan ne contient aucune opération inattendue, sauvegardez une nouvelle fois, puis appliquez les migrations :

```bash
python manage.py migrate --noinput
```

N’utilisez pas `flush`, ne supprimez pas les migrations et ne réinitialisez pas la base. Pour une base réellement neuve seulement, exécutez aussi `python manage.py load_curriculum`; cette commande ajoute les cours et leçons absents sans écraser les contenus déjà enregistrés et rattache les PDF présents quand le champ est vide.

### Choisir MySQL

Utilisez cette option uniquement si le compte permet de créer une base MySQL. Créez d’abord la base dans PythonAnywhere, relevez les valeurs affichées par le compte, puis installez la variante optionnelle :

```bash
cd "$HOME/EduBac/EduBac"
workon edubac-venv
python -m pip install -r requirements-pythonanywhere-mysql.txt
```

Dans `.env`, définissez `DATABASE_ENGINE=mysql`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_HOST` et, si indiqué, `MYSQL_PORT`. Pour préserver une base SQLite existante, ne basculez pas directement la production sur une base MySQL vide : une migration de données est une opération distincte qui doit être répétée et vérifiée sur une copie avant le changement final. La migration de schéma seule ne copie pas les données ni les médias.

## 6. Migrations, statiques et fichiers média

Exécutez les vérifications et la collecte depuis `"$HOME/EduBac/EduBac"` :

```bash
python manage.py check
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py collectstatic --noinput
```

`STATIC_URL` vaut `/static/`, `STATIC_ROOT` pointe vers `EduBac/staticfiles` et `STATICFILES_DIRS` vers `EduBac/static`. Dans l’onglet **Web**, ajoutez la correspondance :

| URL | Dossier |
| --- | --- |
| `/static/` | `/home/<identifiant>/EduBac/EduBac/staticfiles` |

Ne mappez pas `/media/` vers le dossier `media/`. Les fichiers privés et les résultats doivent passer par les vues Django avec leurs contrôles d’accès. La collection statique ne supprime ni ne déplace les médias.

Le dépôt contient les PDF pédagogiques suivis par Git, mais les médias téléversés localement et la base ne sont pas inclus dans le clonage. Vérifiez leur transfert séparément. Gardez les PDF de cours dans la hiérarchie existante `media/lessons/<niveau>/<chapitre>/Cours` ou `Exercices`; les sources IA restent dans `Sources_IA`.

## 7. Configurer WSGI et le site Web

Dans PythonAnywhere, ouvrez **Web**, créez une application Django avec la même version de Python que l’environnement virtuel, puis renseignez le chemin de cet environnement. Dans le fichier WSGI créé par l’interface PythonAnywhere, remplacez son contenu par le raccordement suivant; ce fichier est celui du compte PythonAnywhere, pas `EduBac/config/wsgi.py` :

```python
import os
import sys

PROJECT_DIR = os.path.join(os.path.expanduser('~'), 'EduBac', 'EduBac')
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings_production'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

Dans **Web**, vérifiez également :

1. Le chemin du code source est `~/EduBac/EduBac`.
2. Le fichier WSGI est celui configuré ci-dessus.
3. L’environnement virtuel est `~/.virtualenvs/edubac-venv`.
4. La correspondance statique `/static/` pointe vers `~/EduBac/EduBac/staticfiles`.
5. Le nom de domaine et HTTPS sont activés pour l’application.

Cliquez sur **Reload** après les changements. L’application ne doit pas lancer `migrate` ni `load_curriculum` automatiquement à chaque démarrage.

## 8. Tâches planifiées et fonctionnalités

La commande de rappel des échéances est `send_quiz_reminders`. Si les tâches planifiées sont disponibles dans votre offre, ajoutez une tâche quotidienne avec cette commande :

```bash
cd "$HOME/EduBac/EduBac" && "$HOME/.virtualenvs/edubac-venv/bin/python" manage.py send_quiz_reminders
```

Sur un compte sans tâches planifiées, les rappels automatiques ne seront pas déclenchés par PythonAnywhere; ne remplacez pas cette fonction par un processus permanent lancé dans une console Bash.

| Fonction | WSGI standard | Condition ou remarque |
| --- | --- | --- |
| Authentification EduBac, classes, cours, quiz et résultats | Oui | Google OAuth/allauth n’est pas activé dans le projet actuel. |
| Import/export JSON et Excel | Oui | `openpyxl` figure dans les dépendances. |
| Génération IA | Oui, si l’API est accessible | Configurer une clé côté serveur et vérifier les connexions sortantes du compte. |
| Documents de cours, PDF et pièces jointes | Oui | Servis par Django; ne pas exposer le répertoire média entier. |
| Chat | Partiellement | Les messages sont enregistrés et le client interroge déjà l’API; la diffusion WebSocket instantanée demande ASGI. |
| Tableau blanc collaboratif | Partiellement | Les pages et partages peuvent s’afficher, mais les modifications en direct utilisent WebSocket. |
| Rappels par courriel | Conditionnel | SMTP configuré et tâche planifiée disponible; le backend par défaut n’envoie pas les courriels. |

## 9. Vérification après publication et diagnostic

Après le rechargement, testez :

1. La page d’accueil et la connexion.
2. Un quiz existant, son résultat et les importations/exportations utilisées.
3. L’ouverture d’un PDF pédagogique.
4. Le téléchargement d’une pièce jointe de chat par un membre, puis le refus pour un non-membre.
5. Une génération IA si sa clé et l’accès réseau sont configurés.
6. Le chat avec deux comptes et le tableau blanc; notez la différence entre mise à jour HTTP et collaboration WebSocket.

En cas d’erreur, consultez les journaux **error log** et **server log** de l’onglet Web. Vérifiez d’abord le nom du module de réglages, la version de Python, le chemin de l’environnement virtuel, `ALLOWED_HOSTS`, les origines CSRF, la présence de la base et de `media/`, puis relancez `check --deploy`.

| Symptôme | Vérifications |
| --- | --- |
| Erreur 400 / hôte invalide | `ALLOWED_HOSTS` contient le domaine exact, sans `https://`. |
| Erreur CSRF | `CSRF_TRUSTED_ORIGINS` contient l’origine complète `https://...`; le domaine utilisé correspond à `SITE_URL`. |
| Redirection HTTPS en boucle | Confirmer le proxy HTTPS et `SECURE_PROXY_SSL_HEADER`; ne désactivez la redirection que temporairement pour diagnostiquer. |
| Statique manquant | Relancer `collectstatic`, vérifier `/static/` et le dossier `staticfiles` dans **Web**. |
| PDF ou pièce jointe manquante | Vérifier le transfert de `media/`, la base et les droits du compte; ne pas ajouter de mapping public `/media/`. |
| Génération IA en échec | Vérifier la clé du fournisseur, son nom de modèle, l’accès réseau sortant et les journaux Django sans publier la clé. |
| WebSocket en échec | Un site WSGI classique ne le prend pas en charge; vérifier l’accès ASGI bêta et ses limites avant de changer de serveur. |
| Erreur MySQL | Vérifier les droits de l’offre, `MYSQL_HOST`, le nom de base propre à PythonAnywhere et l’installation de `mysqlclient`. |

## 10. Documentation PythonAnywhere

- [Déploiement Django existant (WSGI)](https://help.pythonanywhere.com/pages/DeployExistingDjangoProject/)
- [Fichiers statiques](https://help.pythonanywhere.com/pages/StaticFiles/)
- [Tâches planifiées](https://help.pythonanywhere.com/pages/ScheduledTasks/)
- [Offres et limites](https://www.pythonanywhere.com/pricing/)
- [Déploiement ASGI expérimental](https://help.pythonanywhere.com/pages/ASGICommandLine/)
