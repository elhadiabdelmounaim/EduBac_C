from django.db import models
from django.conf import settings
import secrets
import string


class Classroom(models.Model):
    """
    Classe gérée par un ou plusieurs enseignants.
    Les élèves rejoignent via un code.
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

    name = models.CharField(max_length=150, verbose_name='Nom de la classe')
    code = models.CharField(
        max_length=12,
        unique=True,
        blank=True,
        verbose_name='Code d\'invitation',
    )
    niveau = models.CharField(
        max_length=50,
        choices=NIVEAU_CHOICES,
        verbose_name='Niveau',
    )
    is_active = models.BooleanField(default=True, verbose_name='Active')
    created_at = models.DateTimeField(auto_now_add=True)
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='managed_classrooms',
        limit_choices_to={'role': 'teacher'},
        verbose_name='Enseignant principal',
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = 'Classe'
        verbose_name_plural = 'Classes'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.code})"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self.create_code()
        super().save(*args, **kwargs)

    @staticmethod
    def create_code(length=8):
        alphabet = string.ascii_uppercase + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    def add_member(self, user):
        if user.role != 'student':
            raise ValueError("Seuls les élèves peuvent rejoindre une classe.")
        # Un élève ne peut appartenir qu'à UNE seule classe
        other = ClassroomMember.objects.filter(user=user).exclude(classroom=self).first()
        if other:
            raise ValueError(
                f"Vous êtes déjà dans la classe « {other.classroom.name} ». "
                "Un élève ne peut rejoindre qu'une seule classe."
            )
        member, created = ClassroomMember.objects.get_or_create(
            classroom=self,
            user=user,
        )
        return member

    def remove_member(self, user):
        ClassroomMember.objects.filter(classroom=self, user=user).delete()


class ClassroomMember(models.Model):
    """
    Lien entre un élève et une classe.
    """
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.CASCADE,
        related_name='members',
        verbose_name='Classe',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='classroom_memberships',
        limit_choices_to={'role': 'student'},
        verbose_name='Élève',
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Membre de classe'
        verbose_name_plural = 'Membres de classe'
        unique_together = ('classroom', 'user')
        ordering = ['-joined_at']

    def __str__(self):
        return f"{self.user.username} dans {self.classroom.name}"

    def leave(self):
        self.delete()
