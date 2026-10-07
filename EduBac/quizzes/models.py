from django.db import models
from django.conf import settings
from education.models import Lesson


class Quiz(models.Model):
    """
    Quiz de mathématiques associé à une leçon.
    """
    DIFFICULTY_CHOICES = [
        ('facile', 'Facile'),
        ('moyen', 'Moyen'),
        ('difficile', 'Difficile'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Brouillon'),
        ('published', 'Publié'),
        ('archived', 'Archivé'),
    ]

    title = models.CharField(max_length=255, verbose_name='Titre')
    description = models.TextField(
        blank=True,
        default='',
        verbose_name='Description du quiz',
        help_text='Notions et types de questions à privilégier lors de la génération IA.',
    )
    duration = models.PositiveIntegerField(
        default=30,
        verbose_name='Durée totale (minutes)',
        help_text='Durée maximale globale en minutes',
    )
    seconds_per_question = models.PositiveIntegerField(
        default=20,
        verbose_name='Secondes par question',
        help_text='Temps alloué à chaque question (ex. 20 s)',
    )
    question_count = models.PositiveIntegerField(
        default=10,
        verbose_name='Nombre de questions',
    )
    difficulty = models.CharField(
        max_length=20,
        choices=DIFFICULTY_CHOICES,
        default='moyen',
        verbose_name='Difficulté',
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft',
        verbose_name='Statut',
    )
    publish_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name='Publication programmée',
        help_text='Si défini, le quiz passera en publié à cette date.',
    )
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name='quizzes',
        verbose_name='Leçon',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_quizzes',
        limit_choices_to={'role': 'teacher'},
    )
    classroom = models.ForeignKey(
        'classrooms.Classroom',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quizzes',
        verbose_name='Classe destinataire',
        help_text='Classe à laquelle ce quiz a été envoyé (si applicable).',
    )

    class Meta:
        verbose_name = 'Quiz'
        verbose_name_plural = 'Quiz'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.get_difficulty_display()})"

    def get_questions(self):
        return self.questions.all().order_by('order')

    def generate_with_ai(self):
        """Déclenché depuis les vues / service IA."""
        pass

    def assign_to_students(self, students):
        for student in students:
            QuizAssignment.objects.get_or_create(quiz=self, student=student)

    def is_assigned_to(self, student):
        """True si l'élève a une affectation pour ce quiz."""
        return self.assignments.filter(student=student).exists()


class QuizGenerationQuestion(models.Model):
    """Persistent novelty history, including generated but not yet saved previews."""
    lesson = models.ForeignKey(
        'education.Lesson', on_delete=models.CASCADE,
        related_name='generated_question_history',
    )
    signature = models.CharField(max_length=64)
    data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['lesson', 'signature'], name='unique_generated_question_per_lesson',
            ),
        ]


class Question(models.Model):
    """
    Question d'un quiz.
    """
    text = models.TextField(verbose_name='Énoncé')
    explanation = models.TextField(blank=True, verbose_name='Explication')
    hint = models.TextField(blank=True, verbose_name='Indice')
    correct_answer = models.CharField(
        max_length=500,
        blank=True,
        verbose_name='Réponse correcte (texte)',
    )
    quiz = models.ForeignKey(
        Quiz,
        on_delete=models.CASCADE,
        related_name='questions',
        verbose_name='Quiz',
    )
    order = models.PositiveIntegerField(default=0, verbose_name='Ordre')

    class Meta:
        verbose_name = 'Question'
        verbose_name_plural = 'Questions'
        ordering = ['quiz', 'order']

    def __str__(self):
        return f"Q{self.order}: {self.text[:60]}..."

    def get_choices(self):
        return self.choices.all().order_by('order')

    def check_answer(self, answer_text):
        """Vérifie si la réponse fournie est correcte."""
        correct_choice = self.choices.filter(is_correct=True).first()
        if correct_choice:
            return answer_text.strip().lower() == correct_choice.text.strip().lower()
        return answer_text.strip().lower() == self.correct_answer.strip().lower()


class Choice(models.Model):
    """
    Choix de réponse pour une question (QCM).
    """
    text = models.CharField(max_length=500, verbose_name='Texte du choix')
    is_correct = models.BooleanField(default=False, verbose_name='Est correct')
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name='choices',
        verbose_name='Question',
    )
    order = models.PositiveIntegerField(default=0, verbose_name='Ordre')

    class Meta:
        verbose_name = 'Choix'
        verbose_name_plural = 'Choix'
        ordering = ['question', 'order']

    def __str__(self):
        marker = '✓' if self.is_correct else '✗'
        return f"{marker} {self.text[:40]}"


class QuizAssignment(models.Model):
    """
    Affectation d'un quiz à un élève.
    """
    assigned_at = models.DateTimeField(auto_now_add=True)
    deadline = models.DateTimeField(null=True, blank=True, verbose_name='Date limite')
    quiz = models.ForeignKey(
        Quiz,
        on_delete=models.CASCADE,
        related_name='assignments',
        verbose_name='Quiz',
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='quiz_assignments',
        limit_choices_to={'role': 'student'},
        verbose_name='Élève',
    )

    class Meta:
        verbose_name = 'Affectation de quiz'
        verbose_name_plural = 'Affectations de quiz'
        unique_together = ('quiz', 'student')
        ordering = ['-assigned_at']

    def __str__(self):
        return f"{self.quiz.title} → {self.student.username}"

    def is_active(self):
        from django.utils import timezone
        if self.deadline and timezone.now() > self.deadline:
            return False
        return True

    def get_students(self):
        return [self.student]


class Attempt(models.Model):
    """
    Tentative d'un élève sur un quiz.
    """
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='attempts',
        limit_choices_to={'role': 'student'},
        verbose_name='Élève',
    )
    quiz = models.ForeignKey(
        Quiz,
        on_delete=models.CASCADE,
        related_name='attempts',
        verbose_name='Quiz',
    )
    started_at = models.DateTimeField(auto_now_add=True)
    teacher_comment = models.TextField(blank=True, verbose_name='Commentaire du professeur')
    submitted_at = models.DateTimeField(null=True, blank=True)
    score = models.FloatField(null=True, blank=True, verbose_name='Score (%)')

    class Meta:
        verbose_name = 'Tentative'
        verbose_name_plural = 'Tentatives'
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.student.username} — {self.quiz.title} ({self.score or 'en cours'}%)"

    def calculate_score(self):
        answers = self.answers.all()
        if not answers.exists():
            self.score = 0.0
        else:
            correct = answers.filter(is_correct=True).count()
            total = answers.count()
            self.score = round((correct / total) * 100, 2)
        self.save(update_fields=['score'])
        return self.score

    def get_answers(self):
        return self.answers.all()

    def start_quiz(self):
        return self

    def submit_answer(self, question, answer_text):
        is_correct = question.check_answer(answer_text)
        return StudentAnswer.objects.create(
            attempt=self,
            question=question,
            answer=answer_text,
            is_correct=is_correct,
        )

    def view_results(self):
        return {
            'score': self.score,
            'answers': self.answers.select_related('question'),
        }


class StudentAnswer(models.Model):
    """
    Réponse d'un élève à une question lors d'une tentative.
    """
    attempt = models.ForeignKey(
        Attempt,
        on_delete=models.CASCADE,
        related_name='answers',
        verbose_name='Tentative',
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name='student_answers',
        verbose_name='Question',
    )
    answer = models.CharField(max_length=500, verbose_name='Réponse donnée')
    is_correct = models.BooleanField(default=False, verbose_name='Correcte')
    explanation = models.TextField(blank=True, verbose_name='Explication affichée')

    class Meta:
        verbose_name = 'Réponse élève'
        verbose_name_plural = 'Réponses élèves'
        unique_together = ('attempt', 'question')

    def __str__(self):
        status = '✓' if self.is_correct else '✗'
        return f"{status} {self.answer[:40]}"

    def verify(self):
        self.is_correct = self.question.check_answer(self.answer)
        self.explanation = self.question.explanation
        self.save()
        return self.is_correct
