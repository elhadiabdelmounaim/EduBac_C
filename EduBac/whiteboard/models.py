from django.conf import settings
from django.db import models


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
        verbose_name='Les élèves peuvent dessiner',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Whiteboard'
        verbose_name_plural = 'Whiteboards'

    def __str__(self):
        return f'{self.title} (#{self.pk})'


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
