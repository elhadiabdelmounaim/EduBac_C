"""Ajout des fichiers (types et taille contrôlés), lecture des formulaires, notifications."""
from datetime import datetime, timedelta
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


# ---------- Travail rendu par l'élève ----------
EXTENSIONS_RENDU = {'pdf', 'png', 'jpg', 'jpeg', 'webp', 'heic', 'heif', 'gif', 'doc', 'docx', 'odt', 'ggb'}
FICHIERS_RENDU_MAX = 15                 # par élève et par devoir


def verifier_fichiers_rendu(fichiers, deja=0):
    if not fichiers:
        raise ErreurDevoir('Choisissez ou photographiez au moins une page.')
    if deja + len(fichiers) > FICHIERS_RENDU_MAX:
        raise ErreurDevoir(f'{FICHIERS_RENDU_MAX} fichiers au plus par devoir.')
    for f in fichiers:
        extension = Path(f.name).suffix.lower().lstrip('.')
        if extension not in EXTENSIONS_RENDU:
            raise ErreurDevoir(f'« {f.name} » : envoyez des photos, un PDF ou un document Word.')
        if f.size > TAILLE_MAX:
            raise ErreurDevoir(f'« {f.name} » dépasse {TAILLE_MAX // (1024 * 1024)} Mo.')
        if not f.size:
            raise ErreurDevoir(f'« {f.name} » est vide.')


def enregistrer_rendu(devoir, eleve, fichiers):
    """Ajoute les pages au travail de l'élève (créé au premier envoi). Renvoie (rendu, nouveau)."""
    from .models import FichierRendu, RenduDevoir
    rendu, nouveau = RenduDevoir.objects.get_or_create(devoir=devoir, eleve=eleve)
    if rendu.corrige_le:
        raise ErreurDevoir('Ce travail est déjà corrigé : il ne peut plus être modifié.')
    verifier_fichiers_rendu(fichiers, deja=0 if nouveau else rendu.fichiers.count())
    crees = []
    try:
        for f in fichiers:
            crees.append(FichierRendu.objects.create(
                rendu=rendu, fichier=f, nom=Path(f.name).name[:255] or 'page', taille=f.size))
    except Exception:
        for c in crees:
            supprimer_fichier(c)
        raise
    rendu.rendu_le = timezone.now()
    rendu.save(update_fields=['rendu_le'])
    return rendu, nouveau


def _nom(user):
    return user.get_full_name() or user.username


def notifier_rendu(rendu):
    """Le professeur : une notification par devoir, regroupée tant qu'elle n'est pas lue."""
    from notifications.services import notify_user
    devoir = rendu.devoir
    retard = ' (en retard)' if rendu.en_retard else ''
    notify_user(
        user=devoir.teacher,
        title='Devoir rendu',
        message=f'{_nom(rendu.eleve)} a rendu « {devoir.titre} »{retard}.',
        type='devoir_rendu',
        actor=rendu.eleve,
        link=reverse('devoirs:rendus', args=[devoir.pk]),
        group_key=f'devoir_rendus:{devoir.pk}',
        send_email=True,
        defer_email=True,
    )


def notifier_correction(rendu):
    from notifications.services import notify_user
    note = f' Note : {rendu.note_texte}/20.' if rendu.note is not None else ''
    notify_user(
        user=rendu.eleve,
        title='Devoir corrigé',
        message=f'Votre travail « {rendu.devoir.titre} » a été corrigé.{note}',
        type='devoir',
        actor=rendu.devoir.teacher,
        link=reverse('devoirs:detail', args=[rendu.devoir_id]) + '#mon-travail',
        send_email=True,
    )


def notifier_ouverture(fichier):
    """« La correction est disponible » pour les élèves des classes du devoir (une seule fois)."""
    from notifications.models import Notification
    from .acces import eleves_des_classes
    devoir = fichier.devoir
    eleves = list(eleves_des_classes(devoir.classes.all()))
    Notification.notify_many(
        eleves,
        title='Document disponible',
        message=f'« {fichier.nom} » est maintenant disponible pour le devoir « {devoir.titre} ».',
        type='devoir',
        actor=devoir.teacher,
        link=reverse('devoirs:detail', args=[devoir.pk]),
        group_key=f'devoir_ouverture:{fichier.pk}',
    )
    type(fichier).objects.filter(pk=fichier.pk).update(ouverture_notifiee=True)
    return len(eleves)


def ouvertures_automatiques():
    """Fichiers dont la date d'ouverture est passée et dont les élèves n'ont pas été prévenus."""
    total = 0
    for fichier in (FichierDevoir.objects.select_related('devoir', 'devoir__teacher')
                    .filter(verrouille=True, ouverture_notifiee=False, ouverture_le__lte=timezone.now())):
        notifier_ouverture(fichier)
        total += 1
    return total


def rappels_devoirs(maintenant=None):
    """Rappel 24 h avant la date limite aux élèves qui n'ont rien rendu (une fois par devoir)."""
    from notifications.models import Notification
    from .acces import eleves_des_classes
    from .models import Devoir
    maintenant = maintenant or timezone.now()
    total = 0
    devoirs = Devoir.objects.filter(
        rendu_en_ligne=True, rappel_envoye_le__isnull=True,
        date_limite__gt=maintenant, date_limite__lte=maintenant + timedelta(hours=24),
    ).select_related('teacher')
    for devoir in devoirs:
        # Marqué d'abord : deux exécutions simultanées n'envoient pas deux rappels.
        if not Devoir.objects.filter(pk=devoir.pk, rappel_envoye_le__isnull=True).update(rappel_envoye_le=maintenant):
            continue
        ont_rendu = devoir.rendus.values('eleve_id')
        eleves = list(eleves_des_classes(devoir.classes.all()).exclude(pk__in=ont_rendu))
        echeance = timezone.localtime(devoir.date_limite)
        total += Notification.notify_many(
            eleves,
            title='Devoir à rendre demain',
            message=f'« {devoir.titre} » est à rendre avant le {echeance:%d/%m à %H:%M}.',
            type='devoir',
            actor=devoir.teacher,
            link=reverse('devoirs:detail', args=[devoir.pk]),
            group_key=f'devoir_rappel:{devoir.pk}',
        )
    return total


def taches_periodiques():
    """Appelé par la commande planifiée et, à défaut, à l'ouverture des pages Devoirs."""
    return {'ouvertures': ouvertures_automatiques(), 'rappels': rappels_devoirs()}
