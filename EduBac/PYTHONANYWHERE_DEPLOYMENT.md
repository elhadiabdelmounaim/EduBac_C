# Audit et préparation du déploiement EduBac sur PythonAnywhere

Ce guide décrit le projet présent dans `EduBac/`. Il prépare un déploiement manuel WSGI; il ne publie, ne transfère et ne migre rien automatiquement. Le compte PythonAnywhere, son offre, son domaine, sa base cible et l’URL publique GitHub restent à confirmer.

## 1. Résumé de l’audit

- Projet Django, vérifié avec Python 3.12.12 et Django 6.1.1. Le projet exige Python 3.12 ou plus.
- SQLite est la configuration locale par défaut. Le projet prend aussi en charge PostgreSQL via `DATABASE_URL` et MySQL via des variables dédiées.
- La base `db.sqlite3` et certains téléversements ne sont pas suivis par Git. Les données et médias existants doivent être transférés séparément, de façon privée.
- Ne rendez pas `MEDIA_ROOT` public. Les pièces jointes, résultats de classe et ressources protégées doivent rester servis par des vues Django soumises aux permissions du projet.
- Le site fonctionne sur WSGI pour les pages HTTP habituelles. Le chat a une actualisation périodique de secours. La collaboration WebSocket en direct du tableau blanc nécessite ASGI et ne fonctionne pas sur le WSGI standard.
- Le dépôt configuré dans ce workspace n’est pas une URL publique clonable. Remplacez le marqueur ci-dessous par l’URL réelle d’un dépôt auquel PythonAnywhere peut accéder.

### Vérifications exécutées

| Vérification | Résultat |
| --- | --- |
| `python manage.py check` | Réussi |
| `python manage.py makemigrations --check --dry-run` | Réussi; aucun changement de modèle requis |
| `python manage.py migrate --check` | Réussi |
| Connexion à la base locale | Réussie |
| Résolution des URL principales et chargement de modèles représentatifs | Réussis |
| `python manage.py collectstatic --noinput` | Réussi; 0 copie et 222 fichiers déjà à jour |
| Tests Django ciblés | 43 tests et 5 tests de sources IA réussis lors des exécutions ciblées |
| Suite Django complète | Non validée : 315 tests détectés, exécution interrompue au délai de 300 secondes avec des échecs visibles dans la sortie partielle |
| Workflow `navbar-browser` | 13 tests, 16 échecs d’assertions de focus clavier; la suite navigateur ne peut pas être déclarée verte |
| `check --deploy` avec réglages de développement | 5 avertissements de déploiement attendus |
| `check --deploy` avec réglages de production factices | Un avertissement HSTS (`SECURE_HSTS_SECONDS=0`), volontaire tant que le domaine n’est pas confirmé |

Les contrôles précédents ne constituent pas une validation de bout en bout sur PythonAnywhere. Les valeurs factices utilisées pour les contrôles de production ne sont pas des identifiants de déploiement.

### Constats de sécurité traités et limites

- Les courriels de notification ne consignent plus l’adresse, le titre du message ni le texte d’exception SMTP; seul le type d’exception est journalisé.
- La commande `backup_db` crée maintenant un instantané SQLite cohérent avec l’API de sauvegarde SQLite, vérifie son intégrité et stocke le fichier avec des permissions privées hors du dépôt. Elle ne copie aucune base non-SQLite.
- Docker Compose n’utilise plus de mot de passe PostgreSQL intégré au fichier et sélectionne explicitement PostgreSQL. Les variables `POSTGRES_*` doivent être définies avant son lancement.
- Les dépendances de déploiement imposent des versions minimales corrigées pour Pillow, certifi, pypdf et AnyIO. Daphne et Playwright sont séparés dans `requirements-dev.txt`; Twisted n’est donc pas nécessaire au déploiement WSGI.
- Le fichier `uv.lock` du workspace conserve les versions précédemment auditées; il n’a pas été régénéré, et les paquets du workspace n’ont pas été réinstallés. Pour PythonAnywhere, suivez les commandes `pip install -r requirements.txt` de ce guide, et non `uv sync`.
- Le scanner de dépendances a compté 40 alertes critiques, 307 élevées, 276 modérées et 14 faibles parmi des sources de dépendances qui se recouvrent; ces nombres ne sont pas des vulnérabilités uniques du déploiement. Dans le verrou du workspace, les alertes critiques/élevées concernent certifi 2026.7.22, Pillow 12.3.0, pypdf 6.19.0 et Twisted 26.4.0. Les exigences de production élèvent les trois premières; Twisted reste dans l’environnement de développement avec Daphne.
- L’alerte SAST concernant `document.write` a été revue : la réponse est le rendu HTML de la vue Django de même origine; le modèle échappe les champs et le filtre LaTeX utilisé dans l’aperçu échappe le texte et le corps des formules. Aucun contenu JSON n’est interprété comme du code. Gardez cette frontière d’échappement lors de toute modification.
- Les alertes relatives aux redirections et aux chemins de fichiers ont été examinées dans le contexte des listes de destinations autorisées et de l’énumération des ressources. Ce contrôle n’est pas un test d’intrusion.

## 2. Limites de l’hébergement à confirmer

PythonAnywhere propose le déploiement Django WSGI standard. L’accès ASGI/WebSocket est expérimental et soumis à l’admissibilité du compte; la documentation de cette option signale des limites pour les fichiers statiques et recommande Uvicorn plutôt que Daphne. Ne changez pas le serveur avant d’avoir testé séparément statiques, sessions, téléchargements et WebSockets.

L’offre, la région et l’ancienneté du compte peuvent modifier la disponibilité de MySQL, des tâches planifiées et des connexions sortantes. Vérifiez les fonctions réellement accessibles dans le compte. Pour un compte gratuit, l’accès aux API IA peut être limité par la liste des domaines sortants autorisés.

## 3. Préparer le dépôt et l’environnement

Dans une console Bash PythonAnywhere, remplacez `<URL_PUBLIQUE_DU_DEPOT>` par l’URL HTTPS ou SSH réelle du dépôt :

```bash
git clone <URL_PUBLIQUE_DU_DEPOT> "$HOME/EduBac"
cd "$HOME/EduBac/EduBac"
python3.12 --version
mkvirtualenv --python=python3.12 edubac-venv
workon edubac-venv
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Choisissez Python 3.12 si cette version est disponible pour le compte. Si elle ne l’est pas, vérifiez d’abord la compatibilité de Django et de chaque dépendance avant de choisir une autre version. Le chemin de l’environnement virtuel à configurer dans l’onglet **Web** est `~/.virtualenvs/edubac-venv`.

Les tests navigateur ne sont pas des dépendances de production. Pour installer localement les outils de développement et de test, utilisez plutôt `python -m pip install -r requirements-dev.txt`.

### Options de base de données

- SQLite est le choix initial qui ne nécessite pas un serveur de base de données.
- Pour MySQL, vérifiez d’abord que le compte peut créer une base, puis installez `python -m pip install -r requirements-pythonanywhere-mysql.txt`. Renseignez `DATABASE_ENGINE=mysql`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_HOST` et éventuellement `MYSQL_PORT`.
- PostgreSQL nécessite un service externe accessible depuis le compte et une `DATABASE_URL` PostgreSQL. PythonAnywhere ne fournit pas PostgreSQL dans son offre standard.
- Changer de moteur ne transfère pas les comptes, quiz, résultats ni médias. Répétez toute conversion sur une copie de préproduction et validez le contenu avant le changement final.

## 4. Secrets et réglages de production

Créez un `.env` privé sur le serveur :

```bash
cd "$HOME/EduBac/EduBac"
cp .env.example .env
chmod 600 .env
nano .env
```

Renseignez au minimum les valeurs suivantes avec votre domaine réel :

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

Générez une clé avec `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` dans l’environnement virtuel, puis collez-la directement dans le `.env` privé. Ne la mettez pas dans Git, dans un fichier WSGI, ni dans des journaux ou captures partagés. Remplacer la clé invalide les sessions signées existantes; les comptes et résultats restent dans la base, mais les utilisateurs devront se reconnecter.

Ajoutez les domaines exacts à `ALLOWED_HOSTS` et les origines HTTPS complètes à `CSRF_TRUSTED_ORIGINS`, séparés par des virgules. Activez et vérifiez HTTPS avant de garder `SECURE_SSL_REDIRECT=True`. Laissez HSTS à zéro jusqu’à ce que HTTPS et le périmètre des sous-domaines soient confirmés; n’activez pas `includeSubDomains` ou `preload` uniquement pour supprimer un avertissement.

La génération IA nécessite une clé privée du fournisseur choisi (`GROQ_API_KEY` par défaut). Les courriels utilisent Gmail SMTP et nécessitent `EMAIL_HOST_USER` ainsi qu’un mot de passe d’application Google stocké dans `EMAIL_HOST_PASSWORD`. Aucun des deux services n’est requis pour les pages de base.

L’accès sortant à `smtp.gmail.com:587` dépend de l’offre et de la configuration du compte PythonAnywhere. Vérifiez-le depuis cet environnement avec `python manage.py check_email`, qui n’envoie aucun message. Si la connexion et l’authentification réussissent, un administrateur peut envoyer un seul test à l’adresse choisie avec `python manage.py check_email --send-test adresse-de-test@example.com`. La livraison n’est confirmée qu’après réception du message.

## 5. Transférer la base et les médias sans perte

### SQLite

La base locale n’est pas incluse dans un clonage Git. Sur l’environnement source, exécutez la sauvegarde SQLite cohérente :

```bash
cd "$HOME/EduBac/EduBac"
python manage.py backup_db
```

Le fichier est enregistré dans `~/backups/edubac/` avec des permissions privées. Transférez-le vers PythonAnywhere par un moyen privé, puis placez-le au chemin configuré par défaut (`$HOME/EduBac/EduBac/db.sqlite3`) ou définissez un chemin absolu via `SQLITE_PATH`. Ne remplacez pas une base déjà utilisée sans la sauvegarder et vérifier son contenu.

Vérifiez le moteur configuré avant de choisir une procédure. Cette commande n’affiche ni URL ni mot de passe :

```bash
python manage.py shell -c "from django.conf import settings; print(settings.DATABASES['default']['ENGINE'])"
```

Si la source est PostgreSQL, ne cherchez pas un fichier SQLite à copier. Une conversion par fixture doit être testée sur une base de préproduction :

```bash
mkdir -p "$HOME/backups/edubac"
python manage.py dumpdata --natural-foreign --natural-primary \
  --exclude contenttypes --exclude auth.permission \
  --output "$HOME/backups/edubac/edubac-data.json"
```

Transférez la fixture de manière privée. Sur une base cible vide, appliquez d’abord les migrations, puis chargez la fixture avec `python manage.py loaddata "$HOME/backups/edubac/edubac-data.json"`. Ne lancez jamais `loaddata` sur une base déjà peuplée et ne lancez pas `load_curriculum` avant l’import. La fixture contient des données de comptes et doit être protégée comme une sauvegarde.

Avant chaque mise à jour, sauvegardez la base avec `python manage.py backup_db` et archivez les médias :

```bash
mkdir -p "$HOME/backups/edubac"
tar -czf "$HOME/backups/edubac/media.$(date +%Y%m%d-%H%M%S).tar.gz" media
```

Transférez séparément les médias ignorés par Git en conservant leurs sous-dossiers. Ne lancez pas `git clean`, ne supprimez pas `media/` et ne décompressez pas une archive sur des fichiers existants sans comparer son contenu.

### Migrations

Après avoir transféré la base correspondant au code, inspectez le plan :

```bash
workon edubac-venv
cd "$HOME/EduBac/EduBac"
python manage.py showmigrations
python manage.py migrate --plan
```

Si le plan ne contient rien d’inattendu et qu’une sauvegarde récente existe, appliquez les migrations :

```bash
python manage.py migrate --noinput
```

N’utilisez pas `flush`, ne supprimez pas les migrations et ne réinitialisez pas une base existante. Exécutez `python manage.py load_curriculum` uniquement lors de l’initialisation d’une base neuve, après avoir vérifié le contenu attendu.

## 6. Contrôles, fichiers statiques et WSGI

Exécutez ces commandes depuis `"$HOME/EduBac/EduBac"` :

```bash
python manage.py check
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py collectstatic --noinput
```

Les avertissements `check --deploy` doivent être évalués selon le domaine et le proxy HTTPS réellement configurés; HSTS à zéro est intentionnel tant que ces paramètres ne sont pas confirmés.

Dans l’onglet **Web**, utilisez l’environnement `~/.virtualenvs/edubac-venv`, le code source `~/EduBac/EduBac` et le fichier WSGI créé par PythonAnywhere. Remplacez son contenu par :

```python
import os
import sys

PROJECT_DIR = os.path.join(os.path.expanduser("~"), "EduBac", "EduBac")
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings_production"

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

Dans **Web**, configurez aussi les fichiers statiques :

| URL | Dossier |
| --- | --- |
| `/static/` | `/home/<identifiant>/EduBac/EduBac/staticfiles` |

`STATIC_ROOT` est `staticfiles/`; `collectstatic` copie les fichiers statiques vers ce dossier. **Ne créez pas de correspondance `/media/`** : les fichiers privés doivent passer par les vues Django et leurs contrôles d’accès. N’exécutez pas `migrate` ou `load_curriculum` automatiquement au démarrage du site.

Rechargez l’application depuis l’onglet **Web** après avoir vérifié le WSGI, l’environnement, les réglages et les chemins.

## 7. Fonctionnalités et tâches planifiées

| Fonction | WSGI standard | Condition |
| --- | --- | --- |
| Connexion EduBac, classes, cours, quiz, résultats et téléchargements protégés | Oui | La base et les médias doivent être transférés. |
| Import/export JSON et Excel | Oui | `openpyxl` est inclus. |
| Génération IA | Oui, conditionnel | Clé configurée et API accessible en sortie. |
| Chat | Partiellement | Interrogation HTTP disponible; la diffusion instantanée requiert WebSocket. |
| Tableau blanc collaboratif | Partiellement | Le direct utilise WebSocket; non pris en charge en WSGI classique. |
| Rappels par courriel | Conditionnel | SMTP configuré et tâche planifiée disponible. |

Si les tâches planifiées sont proposées dans le compte, créez un rappel quotidien :

```bash
cd "$HOME/EduBac/EduBac" && \
  "$HOME/.virtualenvs/edubac-venv/bin/python" manage.py send_quiz_reminders
```

Sans cette fonctionnalité, PythonAnywhere ne déclenchera pas les rappels automatiquement. Ne remplacez pas la tâche par un processus permanent dans une console.

## 8. Vérification après rechargement

Testez manuellement la page d’accueil, la connexion, un quiz existant et son résultat, un PDF pédagogique, l’import/export, puis les permissions d’accès aux pièces jointes avec un membre et un non-membre. Vérifiez la génération IA uniquement si les identifiants et l’accès réseau sont configurés. Testez le chat et le tableau blanc en tenant compte des limites WSGI/WebSocket.

En cas d’erreur, consultez les journaux **error log** et **server log** de l’onglet Web. Vérifiez d’abord le module `config.settings_production`, la version Python, l’environnement virtuel, `ALLOWED_HOSTS`, les origines CSRF, l’existence de la base et le transfert de `media/`. Ne publiez pas les journaux contenant des données de compte.

## 9. Étapes manuelles restantes avant un déploiement

1. Fournir ou configurer une URL publique du dépôt accessible depuis PythonAnywhere.
2. Confirmer l’offre, la région et la version Python proposée par le compte.
3. Choisir le moteur de base cible et décider si les données SQLite existantes doivent être transférées ou converties.
4. Transférer et vérifier la base et les médias privés par un moyen sécurisé; aucun transfert n’a été effectué.
5. Renseigner la clé Django, le domaine, les réglages HTTPS, et, si nécessaire, les clés IA et SMTP dans les secrets du serveur.
6. Décider si l’absence de WebSocket en WSGI est acceptable ou si l’accès au programme ASGI expérimental est nécessaire.
7. Relancer la suite Django complète et les tests navigateur; les résultats actuels ne sont pas tous verts.
8. Configurer et vérifier les tâches planifiées si les rappels par courriel sont requis.
9. Appliquer les migrations uniquement après examen du plan et sauvegarde vérifiée.
10. Effectuer le déploiement et le rechargement manuellement dans le compte; rien n’a été publié ni envoyé depuis ce workspace.

## 10. Références officielles

- [Déployer un projet Django existant (WSGI)](https://help.pythonanywhere.com/pages/DeployExistingDjangoProject/)
- [Fichiers statiques](https://help.pythonanywhere.com/pages/StaticFiles/)
- [Tâches planifiées](https://help.pythonanywhere.com/pages/ScheduledTasks/)
- [Offres et limites](https://www.pythonanywhere.com/pricing/)
- [Déploiement ASGI expérimental](https://help.pythonanywhere.com/pages/ASGICommandLine/)
