"""Diagnostic des notifications sur le téléphone (Web Push).

    python manage.py push_check                  # configuration + appareils enregistrés
    python manage.py push_check --send omar      # envoie un test aux appareils de « omar »
"""
from django.core.management.base import BaseCommand
from django.db import DatabaseError

from accounts.models import User
from notifications import push


class Command(BaseCommand):
    help = 'Vérifie la configuration Web Push et envoie éventuellement une notification de test.'

    def add_arguments(self, parser):
        parser.add_argument('--send', metavar='USERNAME', help='Envoie une notification de test à cet utilisateur.')

    def handle(self, *args, **options):
        ok, bad = self.style.SUCCESS, self.style.ERROR
        self.stdout.write('1. Clés VAPID')
        if not push.is_configured():
            self.stdout.write(bad('   ✗ Absentes : lancez « python manage.py generate_vapid_keys », copiez les 3 lignes '
                                  'dans .env, puis Reload. Sans clés, le bouton « Activer » est caché.'))
            return
        self.stdout.write(ok(f'   ✓ Configurées (publique : {push.public_key()[:12]}…, contact : '
                             f'{push.contact()})'))
        try:
            push._vapid_private_key()
        except Exception as exc:
            self.stdout.write(bad(f'   ✗ Clé privée illisible ({exc}) : régénérez les clés.'))
            return

        self.stdout.write('2. Appareils enregistrés')
        from notifications.models import PushSubscription
        try:
            subscriptions = list(PushSubscription.objects.select_related('user').order_by('user__username'))
        except DatabaseError:
            self.stdout.write(bad('   ✗ Table absente : lancez « python manage.py migrate ».'))
            return
        if not subscriptions:
            self.stdout.write(bad('   ✗ Aucun appareil : chaque élève doit appuyer sur « Activer » (cloche 🔔 ou '
                                  'Préférences) et accepter. Sur iPhone, depuis l’application installée.'))
        for sub in subscriptions:
            last = sub.last_success_at.strftime('%d/%m %H:%M') if sub.last_success_at else 'jamais'
            self.stdout.write(f'   • {sub.user.username:<20} {push.device_label(sub):<32} '
                              f'dernier envoi réussi : {last}, échecs : {sub.failures}')

        username = options.get('send')
        if not username:
            if subscriptions:
                self.stdout.write('   Test : python manage.py push_check --send <nom_utilisateur>')
            return
        self.stdout.write(f'3. Envoi de test à « {username} »')
        user = User.objects.filter(username=username).first()
        if user is None:
            self.stdout.write(bad('   ✗ Utilisateur introuvable.'))
            return
        mine = [s for s in subscriptions if s.user_id == user.pk]
        if not mine:
            self.stdout.write(bad('   ✗ Cet utilisateur n’a activé les notifications sur aucun appareil.'))
            return
        for sub in mine:
            status, error = push.attempt(sub, push.test_payload())
            if status and 200 <= status < 300:
                self.stdout.write(ok(f'   ✓ {push.device_label(sub)} : accepté ({status}).'))
            else:
                hint = ''
                if status is None and ('Proxy' in error or 'URLError' in error or 'Tunnel' in error):
                    hint = (' — le serveur n’arrive pas à joindre le service de push (compte gratuit '
                            'PythonAnywhere : domaine hors liste blanche ?).')
                self.stdout.write(bad(f'   ✗ {push.device_label(sub)} : {error or status}{hint}'))
