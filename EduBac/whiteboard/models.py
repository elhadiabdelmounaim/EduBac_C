from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class WhiteboardBoard(models.Model):
    """
    Tableau blanc lié à une classe (et optionnellement une leçon).
    content = JSON (strokes, shapes, texts, graphs, images).
    """
    title = models.CharField(max_length=200, default='Nouveau tableau')
    classroom = models.ForeignKey(
        'classrooms.Classroom',
        on_delete=models.CASCADE,
        related_name='whiteboards',
        null=True,
        blank=True,
        verbose_name='Classe',
    )
    lesson = models.ForeignKey(
        'education.Lesson',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='whiteboards',
        verbose_name='Leçon',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='whiteboards_created',
    )
    content = models.JSONField(default=dict, blank=True)
    students_can_edit = models.BooleanField(
        default=False,
        verbose_name='Les élèves peuvent participer',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- Partage du tableau vivant -------------------------------------
    ACCESS_CLASS = 'class'
    ACCESS_SELECTED = 'selected'
    ACCESS_CHOICES = [
        (ACCESS_CLASS, 'Toute la classe'),
        (ACCESS_SELECTED, 'Élèves sélectionnés'),
    ]
    access_mode = models.CharField(
        max_length=10, choices=ACCESS_CHOICES, default=ACCESS_CLASS,
        verbose_name='Accès',
    )
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name='shared_whiteboards',
        verbose_name='Élèves invités',
        help_text='Utilisé quand l’accès est limité aux élèves sélectionnés (ou sans classe).',
    )
    editors = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name='whiteboard_edit_grants',
        verbose_name='Élèves autorisés individuellement',
    )

    # --- Permissions des élèves ------------------------------------------
    is_locked = models.BooleanField(default=False, verbose_name='Tableau verrouillé')
    allow_draw = models.BooleanField(default=True, verbose_name='Dessin autorisé')
    allow_text = models.BooleanField(default=True, verbose_name='Écriture autorisée')
    allow_delete = models.BooleanField(default=False, verbose_name='Suppression autorisée')
    allow_images = models.BooleanField(default=False, verbose_name='Images autorisées')
    controller = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='controlled_whiteboards', verbose_name='Élève qui a la main',
    )
    # [{"label": "Groupe 1", "members": [user_id, ...]}, ...] : colonnes de largeur égale.
    zones = models.JSONField(default=list, blank=True, verbose_name='Espaces de travail')
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Whiteboard'
        verbose_name_plural = 'Whiteboards'

    def __str__(self):
        return f'{self.title} (#{self.pk})'


class WhiteboardOp(models.Model):
    """Une modification appliquée au tableau (synchronisation et contributions)."""

    board = models.ForeignKey(WhiteboardBoard, on_delete=models.CASCADE, related_name='ops')
    revision = models.PositiveIntegerField()
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+',
    )
    client = models.CharField(max_length=64, blank=True)
    kind = models.CharField(max_length=20)
    object_id = models.CharField(max_length=100, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['revision']
        constraints = [
            models.UniqueConstraint(fields=['board', 'revision'], name='unique_whiteboard_op_revision'),
        ]


class WhiteboardPresence(models.Model):
    """Participant d'un tableau : présence, curseur, main levée, contributions."""

    board = models.ForeignKey(WhiteboardBoard, on_delete=models.CASCADE, related_name='presences')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    last_seen = models.DateTimeField(default=timezone.now)
    cursor_x = models.FloatField(null=True, blank=True)
    cursor_y = models.FloatField(null=True, blank=True)
    hand_raised_at = models.DateTimeField(null=True, blank=True)
    contributions = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['board', 'user'], name='unique_whiteboard_presence'),
        ]


class WhiteboardShare(models.Model):
    """Image PNG d'un tableau, envoyée à une seule classe."""

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='whiteboard_shares',
        verbose_name='Enseignant',
    )
    classroom = models.ForeignKey(
        'classrooms.Classroom',
        on_delete=models.CASCADE,
        related_name='whiteboard_shares',
        verbose_name='Classe',
    )
    image = models.ImageField(
        upload_to='whiteboards/shares/%Y/%m/',
        verbose_name='Image',
    )
    title = models.CharField(max_length=200, default='Whiteboard', verbose_name='Titre')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Partagé le')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Whiteboard partagé'
        verbose_name_plural = 'Whiteboards partagés'
        indexes = [
            models.Index(fields=['classroom', '-created_at']),
        ]

    def __str__(self):
        return f'{self.title} → {self.classroom_id}'

    def when_label(self):
        local = timezone.localtime(self.created_at)
        today = timezone.localdate()
        if local.date() == today:
            day = 'Aujourd’hui'
        elif local.date() == today - timedelta(days=1):
            day = 'Hier'
        else:
            day = local.strftime('%d/%m/%Y')
        return f'{day} {local.strftime("%H:%M")}'


class QuizCorrectionBoard(models.Model):
    """
    Tableau de correction pédagogique lié à une tentative + question.
    data = document JSON validé (schema v1).
    N'écrit jamais dans Attempt / StudentAnswer / score.
    """
    attempt = models.ForeignKey(
        'quizzes.Attempt',
        on_delete=models.CASCADE,
        related_name='correction_boards',
    )
    question = models.ForeignKey(
        'quizzes.Question',
        on_delete=models.CASCADE,
        related_name='correction_boards',
    )
    data = models.JSONField(default=dict, blank=True)
    schema_version = models.PositiveSmallIntegerField(default=1)
    revision = models.PositiveIntegerField(default=1)
    mode = models.CharField(
        max_length=10,
        choices=[('hint', 'Indice'), ('full', 'Correction complète')],
        default='full',
    )
    generated_by_ai = models.BooleanField(default=False)
    warning = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Tableau de correction'
        verbose_name_plural = 'Tableaux de correction'
        unique_together = ('attempt', 'question')
        ordering = ['-updated_at']

    def __str__(self):
        return f'Correction attempt={self.attempt_id} q={self.question_id} r{self.revision}'
