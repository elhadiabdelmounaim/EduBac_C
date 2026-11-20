"""Convertit des tableaux de l'ancien module en documents du tableau mathématique.

    python manage.py mathboard_convert_legacy --board 12
    python manage.py mathboard_convert_legacy --all          # tous ceux pas encore convertis

Les anciens tableaux ne sont ni modifiés ni supprimés.
"""
from django.core.management.base import BaseCommand, CommandError

from mathboard.legacy import convert_board
from mathboard.models import WhiteboardDocument


class Command(BaseCommand):
    help = 'Copie des tableaux de l’ancien module dans le tableau mathématique.'

    def add_arguments(self, parser):
        parser.add_argument('--board', type=int, action='append', help='Identifiant d’un ancien tableau (répétable).')
        parser.add_argument('--all', action='store_true', help='Tous les anciens tableaux actifs pas encore convertis.')

    def handle(self, *args, board=None, all=False, **options):
        from whiteboard.models import WhiteboardBoard
        if not board and not all:
            raise CommandError('Indiquez --board <id> ou --all.')
        boards = WhiteboardBoard.objects.filter(is_active=True).select_related('created_by', 'classroom', 'lesson')
        boards = boards.filter(pk__in=board) if board else boards
        done = 0
        for old in boards:
            if WhiteboardDocument.objects.filter(legacy_board=old, owner=old.created_by).exists():
                self.stdout.write(f'#{old.pk} « {old.title} » : déjà converti.')
                continue
            document, report = convert_board(old, old.created_by)
            skipped = ', '.join(f'{n} {kind}' for kind, n in sorted(report['skipped'].items())) or 'rien'
            self.stdout.write(f'#{old.pk} « {old.title} » → document #{document.pk} : '
                              f'{report["converted"]} élément(s) ; non repris : {skipped}.')
            done += 1
        self.stdout.write(self.style.SUCCESS(f'{done} tableau(x) converti(s).'))
