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
    rendu_en_ligne = models.BooleanField(
        'Rendu en ligne demandé', default=True,
        help_text='Les élèves déposent leur travail (photos ou PDF) dans EduBac.',
    )
    rappel_envoye_le = models.DateTimeField(null=True, blank=True, editable=False)
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
    # Les élèves ont été prévenus de l'ouverture (à la main ou à la date d'ouverture).
    ouverture_notifiee = models.BooleanField(default=False, editable=False)
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


class RenduDevoir(models.Model):
    """Travail d'un élève pour un devoir (une copie par élève, complétable jusqu'à la correction)."""
    devoir = models.ForeignKey(Devoir, on_delete=models.CASCADE, related_name='rendus')
    eleve = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='rendus_devoirs')
    rendu_le = models.DateTimeField('Rendu le', default=timezone.now)
    note = models.DecimalField('Note /20', max_digits=4, decimal_places=2, null=True, blank=True)
    commentaire = models.TextField('Commentaire du professeur', blank=True)
    corrige_le = models.DateTimeField('Corrigé le', null=True, blank=True)

    class Meta:
        ordering = ['devoir', 'eleve__last_name', 'eleve__first_name']
        constraints = [models.UniqueConstraint(fields=['devoir', 'eleve'], name='un_rendu_par_eleve')]
        verbose_name = 'Travail rendu'
        verbose_name_plural = 'Travaux rendus'

    def __str__(self):
        return f'{self.eleve} — {self.devoir}'

    @property
    def note_texte(self):
        """15.50 → « 15,5 » ; 16.00 → « 16 »."""
        if self.note is None:
            return ''
        return f'{self.note.normalize():f}'.replace('.', ',')

    @property
    def en_retard(self):
        return bool(self.devoir.date_limite and self.rendu_le > self.devoir.date_limite)


def chemin_rendu(instance, filename):
    extension = Path(filename).suffix.lower()[:10]
    return f'devoirs/{instance.rendu.devoir_id}/rendus/{uuid.uuid4().hex}{extension}'


class FichierRendu(models.Model):
    rendu = models.ForeignKey(RenduDevoir, on_delete=models.CASCADE, related_name='fichiers')
    fichier = models.FileField(upload_to=chemin_rendu, max_length=255)
    nom = models.CharField(max_length=255)
    taille = models.PositiveIntegerField(default=0)
    ajoute_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['ajoute_le', 'pk']
        verbose_name = 'Fichier rendu'
        verbose_name_plural = 'Fichiers rendus'

    def __str__(self):
        return self.nom

    @property
    def extension(self):
        return Path(self.nom).suffix.lower().lstrip('.')
