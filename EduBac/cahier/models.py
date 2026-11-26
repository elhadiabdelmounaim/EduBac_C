"""Cahier de textes : ce que l'enseignant a traité, par classe, leçon et date."""
from django.conf import settings
from django.db import models


class Seance(models.Model):
    """Une séance : une leçon traitée avec une classe à une date donnée.
    Enregistrer de nouveau la même date met la séance à jour (pas de doublon)."""
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='seances_cahier', verbose_name='Enseignant')
    classroom = models.ForeignKey('classrooms.Classroom', on_delete=models.CASCADE,
                                  related_name='seances_cahier', verbose_name='Classe')
    lesson = models.ForeignKey('education.Lesson', on_delete=models.CASCADE,
                               related_name='seances_cahier', verbose_name='Leçon')
    date = models.DateField(verbose_name='Date')
    observations = models.TextField(blank=True, verbose_name='Observations')
    duree_minutes = models.PositiveIntegerField(
        null=True, blank=True, verbose_name='Durée réalisée (min)',
        help_text='Vide (séances anciennes) : durée prévue des éléments traités.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Séance'
        verbose_name_plural = 'Séances'
        ordering = ['-date', '-updated_at']
        constraints = [
            models.UniqueConstraint(fields=['teacher', 'classroom', 'lesson', 'date'],
                                    name='cahier_seance_unique_par_jour'),
        ]

    def __str__(self):
        return f'{self.date:%d/%m/%Y} · {self.classroom.name} · {self.lesson.title}'


class SeanceElement(models.Model):
    """Un élément traité (définition, proposition, exemples…). Les titres de la partie et
    du sous-titre sont copiés : le cahier reste lisible même si le cours change."""
    seance = models.ForeignKey(Seance, on_delete=models.CASCADE, related_name='elements')
    key = models.CharField(max_length=40, verbose_name='Clé')
    title = models.CharField(max_length=255, verbose_name='Élément')
    partie = models.CharField(max_length=255, verbose_name='Partie')
    sous_titre = models.CharField(max_length=255, blank=True, verbose_name='Sous-titre')
    order = models.PositiveIntegerField(default=0, verbose_name='Ordre')
    minutes = models.PositiveIntegerField(default=0, verbose_name='Durée prévue (min)')

    class Meta:
        verbose_name = 'Élément traité'
        verbose_name_plural = 'Éléments traités'
        ordering = ['order']
        constraints = [
            models.UniqueConstraint(fields=['seance', 'key'], name='cahier_element_unique'),
        ]

    def __str__(self):
        return self.title


class AccesLecon(models.Model):
    """Accès des élèves d'une classe à une leçon (cours, PDF, exercices).

    La leçon s'ouvre d'elle-même quand le cahier de textes de la classe couvre tout son plan
    (`termine_auto`) ; la décision du professeur (`decision`), si elle existe, l'emporte dans
    les deux sens. Sans ligne : leçon verrouillée."""
    OUVERT = 'ouvert'
    FERME = 'ferme'
    DECISIONS = [('', 'Automatique (cahier de textes)'), (OUVERT, 'Ouverte'), (FERME, 'Verrouillée')]

    classroom = models.ForeignKey('classrooms.Classroom', on_delete=models.CASCADE,
                                  related_name='acces_lecons', verbose_name='Classe')
    lesson = models.ForeignKey('education.Lesson', on_delete=models.CASCADE,
                               related_name='acces_classes', verbose_name='Leçon')
    termine_auto = models.BooleanField(default=False, verbose_name='Plan terminé (cahier)')
    decision = models.CharField(max_length=10, choices=DECISIONS, blank=True, default='',
                                verbose_name='Décision du professeur')
    decide_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='+', verbose_name='Décidé par')
    ouverte_le = models.DateTimeField(null=True, blank=True, verbose_name='Ouverte aux élèves le')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Accès à une leçon'
        verbose_name_plural = 'Accès aux leçons'
        constraints = [
            models.UniqueConstraint(fields=['classroom', 'lesson'], name='cahier_acces_unique'),
        ]

    def __str__(self):
        return f'{self.classroom} · {self.lesson.title} · {"ouverte" if self.est_ouverte else "verrouillée"}'

    @property
    def est_ouverte(self):
        if self.decision:
            return self.decision == self.OUVERT
        return self.termine_auto
