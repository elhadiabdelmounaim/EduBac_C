"""Devoirs : le professeur publie un devoir (consigne, date limite) pour une ou plusieurs de ses
classes, avec des fichiers. Un fichier peut rester verrouillé (une correction, par exemple) :
les élèves en voient le nom mais ne peuvent l'ouvrir qu'une fois déverrouillé, à la main ou à
la date d'ouverture choisie."""
import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone


class Devoir(models.Model):
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='devoirs_crees',
        verbose_name='Professeur',
    )
    titre = models.CharField('Titre', max_length=200)
    consigne = models.TextField('Consigne', blank=True)
    date_limite = models.DateTimeField('À rendre le', null=True, blank=True)
    classes = models.ManyToManyField('classrooms.Classroom', related_name='devoirs', verbose_name='Classes')
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-cree_le', '-pk']
        verbose_name = 'Devoir'
        verbose_name_plural = 'Devoirs'

    def __str__(self):
        return self.titre


def chemin_fichier(instance, filename):
    """Nom imprévisible sur le disque ; le nom d'origine est gardé dans « nom »."""
    extension = Path(filename).suffix.lower()[:10]
    return f'devoirs/{instance.devoir_id}/{uuid.uuid4().hex}{extension}'


class FichierDevoir(models.Model):
    devoir = models.ForeignKey(Devoir, on_delete=models.CASCADE, related_name='fichiers')
    fichier = models.FileField(upload_to=chemin_fichier, max_length=255)
    nom = models.CharField('Nom', max_length=255)
    taille = models.PositiveIntegerField(default=0)
    verrouille = models.BooleanField('Verrouillé', default=False)
    ouverture_le = models.DateTimeField(
        "Ouverture automatique", null=True, blank=True,
        help_text='Un fichier verrouillé devient visible pour les élèves à cette date.',
    )
    ajoute_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['ajoute_le', 'pk']
        verbose_name = 'Fichier de devoir'
        verbose_name_plural = 'Fichiers de devoir'

    def __str__(self):
        return self.nom

    def est_visible(self, maintenant=None):
        """Visible par les élèves : non verrouillé, ou date d'ouverture automatique passée."""
        if not self.verrouille:
            return True
        return bool(self.ouverture_le and self.ouverture_le <= (maintenant or timezone.now()))

    @property
    def extension(self):
        return Path(self.nom).suffix.lower().lstrip('.')
