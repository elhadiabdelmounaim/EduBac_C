"""Ajout des fichiers (types et taille contrôlés), lecture des formulaires, notifications."""
from datetime import datetime
from pathlib import Path

from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import FichierDevoir

TAILLE_MAX = 20 * 1024 * 1024          # 20 Mo par fichier
FICHIERS_MAX = 20                      # par envoi
EXTENSIONS = {
    'pdf', 'png', 'jpg', 'jpeg', 'webp', 'gif',
    'doc', 'docx', 'odt', 'rtf', 'txt',
    'ppt', 'pptx', 'odp', 'xls', 'xlsx', 'ods', 'csv',
    'ggb', 'zip',
}
# Ouverts dans le navigateur ; les autres sont téléchargés.
EN_LIGNE = {'pdf': 'application/pdf', 'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
            'webp': 'image/webp', 'gif': 'image/gif', 'txt': 'text/plain; charset=utf-8'}


class ErreurDevoir(ValueError):
    """Message à afficher au professeur."""


def lire_date(brut, nom='La date'):
    """Champ datetime-local → date avec fuseau ; None si vide."""
    brut = (brut or '').strip()
    if not brut:
        return None
    valeur = parse_datetime(brut)
    if valeur is None:
        try:
            valeur = datetime.strptime(brut, '%Y-%m-%dT%H:%M')
        except ValueError:
            raise ErreurDevoir(f'{nom} n’est pas valide.') from None
    if timezone.is_naive(valeur):
        valeur = timezone.make_aware(valeur)
    return valeur


def verifier_fichiers(fichiers):
    if len(fichiers) > FICHIERS_MAX:
        raise ErreurDevoir(f'{FICHIERS_MAX} fichiers au plus par envoi.')
    for f in fichiers:
        extension = Path(f.name).suffix.lower().lstrip('.')
        if extension not in EXTENSIONS:
            raise ErreurDevoir(f'« {f.name} » : type de fichier non accepté '
                               '(PDF, images, Word, PowerPoint, Excel, GeoGebra, ZIP…).')
        if f.size > TAILLE_MAX:
            raise ErreurDevoir(f'« {f.name} » dépasse {TAILLE_MAX // (1024 * 1024)} Mo.')
        if not f.size:
            raise ErreurDevoir(f'« {f.name} » est vide.')


def ajouter_fichiers(devoir, fichiers, verrouille=False, ouverture_le=None):
    """Enregistre les fichiers (déjà vérifiés). Si l'un échoue, ceux déjà écrits sont retirés."""
    crees = []
    try:
        for f in fichiers:
            nom = Path(f.name).name[:255] or 'fichier'
            crees.append(FichierDevoir.objects.create(
                devoir=devoir, fichier=f, nom=nom, taille=f.size,
                verrouille=verrouille, ouverture_le=ouverture_le if verrouille else None,
            ))
    except Exception:
        for fichier in crees:
            supprimer_fichier(fichier)
        raise
    return crees


def supprimer_fichier(fichier):
    """Supprime l'enregistrement et le fichier sur le disque (après validation de la transaction)."""
    stockage, chemin = fichier.fichier.storage, fichier.fichier.name
    fichier.delete()
    if chemin:
        transaction.on_commit(lambda: stockage.delete(chemin) if stockage.exists(chemin) else None)


def notifier_nouveau_devoir(devoir, eleves):
    """« Nouveau devoir » (dans EduBac et sur le téléphone) pour chaque élève, une seule fois."""
    from notifications.services import notify_user
    echeance = ''
    if devoir.date_limite:
        echeance = f' À rendre le {timezone.localtime(devoir.date_limite):%d/%m/%Y à %H:%M}.'
    lien = reverse('devoirs:detail', args=[devoir.pk])
    for eleve in eleves:
        notify_user(
            user=eleve,
            title='Nouveau devoir',
            message=f'« {devoir.titre} » a été publié.{echeance}',
            type='devoir',
            actor=devoir.teacher,
            link=lien,
            send_email=True,
        )
