"""Page d'état pour l'administrateur : ce qui est configuré, ce qui manque (sans aucun secret)."""
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.shortcuts import render
from django.utils import timezone

from .decorators import admin_required


def _check(label, ok, detail, fix=''):
    return {'label': label, 'ok': ok, 'detail': detail, 'fix': fix}


def _version():
    git = Path(settings.BASE_DIR).parent / '.git'
    try:
        head = (git / 'HEAD').read_text().strip()
        if head.startswith('ref:'):
            head = (git / head[5:]).read_text().strip()
        return head[:7]
    except OSError:
        return 'inconnue'


def _last_backup():
    folder = Path.home() / 'backups' / 'edubac'
    files = sorted(folder.glob('db_*.sqlite3')) if folder.exists() else []
    if not files:
        return None
    return timezone.datetime.fromtimestamp(files[-1].stat().st_mtime, tz=timezone.get_current_timezone())


@admin_required
def system_status(request):
    from config.site_info import missing_fields
    from notifications import push
    from notifications.models import PushSubscription

    checks = []
    executor = MigrationExecutor(connection)
    pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    checks.append(_check('Base de données', not pending,
                         'À jour' if not pending else f'{len(pending)} migration(s) à appliquer',
                         'python manage.py migrate'))
    backup = _last_backup()
    fresh = bool(backup and (timezone.now() - backup).days < 2)
    checks.append(_check('Sauvegarde', fresh,
                         f'Dernière : {timezone.localtime(backup):%d/%m/%Y %H:%M}' if backup else 'Aucune sauvegarde trouvée',
                         'Tâche planifiée quotidienne : python manage.py backup_db'))
    email_ok = bool(settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD) or 'console' in settings.EMAIL_BACKEND
    checks.append(_check('E-mails', email_ok,
                         f'Serveur {settings.EMAIL_HOST}' if email_ok else 'Identifiants SMTP absents',
                         'EMAIL_HOST_USER et EMAIL_HOST_PASSWORD dans .env, puis python manage.py check_email'))
    checks.append(_check('Alerte des erreurs', bool(settings.ADMINS),
                         'Les erreurs serveur sont envoyées par e-mail' if settings.ADMINS else 'Personne n’est prévenu en cas d’erreur',
                         'ADMIN_EMAIL=votre@adresse dans .env'))
    devices = PushSubscription.objects.count() if push.is_configured() else 0
    checks.append(_check('Notifications du téléphone', push.is_configured(),
                         f'{devices} appareil(s) enregistré(s)' if push.is_configured() else 'Clés VAPID absentes',
                         'python manage.py generate_vapid_keys, puis les 3 lignes dans .env'))
    missing = missing_fields()
    checks.append(_check('Pages légales', not missing,
                         'Complètes' if not missing else 'À compléter : ' + ', '.join(missing),
                         'config/site_info.py'))
    checks.append(_check('Mode production', not settings.DEBUG,
                         'DEBUG désactivé' if not settings.DEBUG else 'DEBUG activé : les erreurs détaillées sont visibles',
                         'DJANGO_PRODUCTION=1 dans .env'))
    return render(request, 'accounts/system_status.html', {
        'page_title': 'État du site',
        'checks': checks,
        'version': _version(),
        'ok_count': sum(1 for c in checks if c['ok']),
    })
