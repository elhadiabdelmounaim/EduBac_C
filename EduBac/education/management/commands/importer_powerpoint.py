"""Range les présentations PowerPoint d'un ZIP (EduBac_PowerPoint_cours.zip) dans les leçons.

Le ZIP contient <Niveau>/<NN>_<Titre>.pptx (ex. 1ere_Bac_Sciences/04_Le_produit_scalaire_dans_le_plan.pptx).
Chaque fichier va à la leçon du même niveau, du même numéro et du même titre ; sinon il est signalé.
Usage : python manage.py importer_powerpoint chemin/vers/EduBac_PowerPoint_cours.zip [--essai]
"""
import re
import tempfile
import unicodedata
import zipfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from education import powerpoint
from education.models import Lesson

DOSSIERS = {
    '1ere_bac_sciences': '1ere_bac_sc',
    'tronc_commun_scientifique': 'tronc_commun',
    'tronc_commun': 'tronc_commun',
    '1ere_bac_sciences_mathematiques': '1ere_bac_sm',
    '2eme_bac_sciences': '2eme_bac_sc',
}


def _cle(texte):
    texte = unicodedata.normalize('NFKD', texte).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '', texte)


class Command(BaseCommand):
    help = 'Associe les présentations PowerPoint d’un ZIP aux leçons (réservées aux professeurs).'

    def add_arguments(self, parser):
        parser.add_argument('zip', help='Fichier ZIP produit par EduBac (EduBac_PowerPoint_cours.zip).')
        parser.add_argument('--essai', action='store_true', help='Afficher sans rien écrire.')

    def handle(self, *args, zip=None, essai=False, **options):
        chemin = Path(zip)
        if not chemin.is_file():
            raise CommandError(f'Fichier introuvable : {chemin}')
        lecons = list(Lesson.objects.select_related('course'))
        owners = {}
        from django.utils.text import slugify
        for l in sorted(lecons, key=lambda l: (l.course.order, l.course_id, l.pk)):
            owners.setdefault((l.course.niveau, l.order, slugify(l.title)[:160] or 'lecon'), l.pk)
        index = {(l.course.niveau, l.order, _cle(l.title)): l for l in lecons}
        ranges, ignores = 0, 0
        with zipfile.ZipFile(chemin) as archive, tempfile.TemporaryDirectory() as dossier:
            for info in archive.infolist():
                nom = Path(info.filename)
                if info.is_dir() or nom.suffix.lower() != '.pptx' or len(nom.parts) < 2:
                    continue
                niveau = DOSSIERS.get(nom.parent.name.lower())
                m = re.match(r'(\d+)_(.+)\.pptx$', nom.name, re.I)
                lecon = index.get((niveau, int(m.group(1)), _cle(m.group(2)))) if niveau and m else None
                if lecon is None:
                    ignores += 1
                    self.stdout.write(self.style.WARNING(f'  ? {info.filename} : aucune leçon correspondante'))
                    continue
                if essai:
                    self.stdout.write(f'  = {info.filename} → {lecon.title} ({lecon.course.get_niveau_display()})')
                    ranges += 1
                    continue
                extrait = Path(dossier) / 'diapos.pptx'
                with archive.open(info) as entree, open(extrait, 'wb') as sortie:
                    while bloc := entree.read(1024 * 1024):
                        sortie.write(bloc)
                powerpoint.remplacer(lecon, extrait, owners)
                ranges += 1
                self.stdout.write(f'  + {lecon.title} ({lecon.course.get_niveau_display()})')
        self.stdout.write(self.style.SUCCESS(
            f'{ranges} présentation(s) {"trouvée(s)" if essai else "rangée(s)"}, {ignores} ignorée(s).'))
