from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Utilisateur personnalisé EduBac.
    Rôles : student (élève) ou teacher (enseignant).
    """
    ROLE_CHOICES = [
        ('student', 'Élève'),
        ('teacher', 'Enseignant'),
    ]
    APPROVAL_STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('approved', 'Approuvé'),
    ]

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='student',
        verbose_name='Rôle',
    )
    email = models.EmailField(
        unique=True,
        blank=True,
        null=True,
        verbose_name='Adresse e-mail',
    )
    email_verified = models.BooleanField(
        default=True,
        verbose_name='Adresse e-mail vérifiée',
    )
    approval_status = models.CharField(
        max_length=20,
        choices=APPROVAL_STATUS_CHOICES,
        default='approved',
        verbose_name='Statut d’approbation',
    )
    must_change_password = models.BooleanField(
        default=False,
        verbose_name='Doit changer son mot de passe',
    )
    password_reset_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Dernière réinitialisation administrateur',
    )
    password_session_version = models.PositiveIntegerField(
        default=0,
        editable=False,
    )

    class Meta:
        verbose_name = 'Utilisateur'
        verbose_name_plural = 'Utilisateurs'

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    def is_student(self):
        return (
            self.role == 'student'
            and not self.is_staff
            and not self.is_superuser
        )

    def is_teacher(self):
        return (
            self.role == 'teacher'
            or self.is_staff
            or self.is_superuser
        )

    def get_role_display(self):
        if self.is_teacher():
            return 'Enseignant'
        return dict(self.ROLE_CHOICES).get(self.role, self.role)

    def get_full_name(self):
        full = f"{self.first_name} {self.last_name}".strip()
        return full if full else self.username


class StudentPasswordResetEvent(models.Model):
    """Audit trail without retaining the temporary password."""

    student = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='password_reset_events',
    )
    student_username = models.CharField(max_length=150)
    administrator = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='student_password_resets',
    )
    administrator_id_snapshot = models.PositiveBigIntegerField()
    administrator_username = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'Réinitialisation de mot de passe élève'
        verbose_name_plural = 'Réinitialisations de mots de passe élèves'

    def __str__(self):
        return f'{self.student_username} — {self.created_at:%Y-%m-%d %H:%M}'


class StudentProfile(models.Model):
    """
    Profil élève : niveau scolaire et progression.
    """
    NIVEAU_CHOICES = [
        ('tronc_commun', 'Tronc Commun'),
        ('1ere_bac_sc', '1ère Bac Sciences'),
        ('1ere_bac_sm', '1ère Bac Sciences Mathématiques'),
        ('1ere_bac_lettres', '1ère Bac Lettres'),
        ('2eme_bac_svt', '2ème Bac SVT'),
        ('2eme_bac_pc', '2ème Bac PC'),
        ('2eme_bac_lettres', '2ème Bac Lettres'),
        ('2eme_bac_sm', '2ème Bac Sciences Mathématiques'),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='student_profile',
        limit_choices_to={'role': 'student'},
    )
    niveau = models.CharField(
        max_length=50,
        choices=NIVEAU_CHOICES,
        default='tronc_commun',
        verbose_name='Niveau scolaire',
    )
    progress = models.FloatField(default=0.0, verbose_name='Progression (%)')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Profil élève'
        verbose_name_plural = 'Profils élèves'

    def __str__(self):
        return f"Profil de {self.user.username} — {self.get_niveau_display()}"

    def get_courses(self):
        from education.models import Course
        return Course.objects.filter(niveau=self.niveau)

    def get_quizzes(self):
        from quizzes.models import QuizAssignment
        return QuizAssignment.objects.filter(student=self.user)

    def get_progress(self):
        return self.progress


class TeacherProfile(models.Model):
    """
    Profil enseignant. Sujet toujours Mathématiques.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='teacher_profile',
        limit_choices_to={'role': 'teacher'},
    )
    subject = models.CharField(
        max_length=100,
        default='Mathématiques',
        verbose_name='Matière',
    )
    bio = models.TextField(blank=True, verbose_name='Biographie')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Profil enseignant'
        verbose_name_plural = 'Profils enseignants'

    def __str__(self):
        return f"Enseignant {self.user.username} — {self.subject}"



class Badge(models.Model):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    icon = models.CharField(max_length=20, default='🏅')

    def __str__(self):
        return self.name


class UserBadge(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='badges')
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE)
    earned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'badge')


class DailyActivity(models.Model):
    """Pour la série de jours (streak)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='daily_activities')
    day = models.DateField()
    quiz_count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('user', 'day')


class FavoriteLesson(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='favorite_lessons')
    lesson = models.ForeignKey('education.Lesson', on_delete=models.CASCADE, related_name='favorited_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'lesson')



class WeeklyChallenge(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    target_quizzes = models.PositiveIntegerField(default=3)
    theme = models.CharField(max_length=100, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.title
