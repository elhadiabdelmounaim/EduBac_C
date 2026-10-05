from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Notification(models.Model):
    """
    Notification utilisateur EduBac.
    Types : quiz assigné, résultat, classe, système, IA, etc.
    """
    TYPE_CHOICES = [
        ('quiz_assigned', 'Quiz assigné'),
        ('quiz_result', 'Résultat de quiz'),
        ('classroom', 'Classe'),
        ('lesson', 'Leçon'),
        ('ai', 'Assistant IA'),
        ('system', 'Système'),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name='Destinataire',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications_sent',
        verbose_name='Auteur',
    )
    type = models.CharField(
        max_length=30,
        choices=TYPE_CHOICES,
        default='system',
        verbose_name='Type',
    )
    title = models.CharField(max_length=200, verbose_name='Titre')
    message = models.TextField(verbose_name='Message')
    link = models.CharField(
        max_length=500,
        blank=True,
        verbose_name='Lien relatif',
        help_text='Ex. : /quizzes/5/',
    )
    is_read = models.BooleanField(default=False, verbose_name='Lu')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Créée le')

    class Meta:
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read', '-created_at']),
        ]

    def __str__(self):
        status = '✓' if self.is_read else '●'
        return f"{status} {self.title} → {self.recipient.username}"

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=['is_read'])

    @property
    def time_ago(self):
        """Texte relatif simple en français."""
        delta = timezone.now() - self.created_at
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "À l'instant"
        minutes = seconds // 60
        if minutes < 60:
            return f"Il y a {minutes} min"
        hours = minutes // 60
        if hours < 24:
            return f"Il y a {hours} h"
        days = hours // 24
        if days == 1:
            return "Hier"
        if days < 7:
            return f"Il y a {days} j"
        return self.created_at.strftime('%d/%m/%Y')

    @classmethod
    def notify(cls, recipient, title, message, type='system', actor=None, link='', send_email=True):
        """Crée une notification in-app et envoie un e-mail si demandé."""
        obj = cls.objects.create(
            recipient=recipient,
            actor=actor,
            type=type,
            title=title,
            message=message,
            link=link or '',
        )
        if send_email:
            try:
                from .email_utils import send_notification_email
                send_notification_email(
                    recipient=recipient,
                    title=title,
                    message=message,
                    link=link or '',
                    type_code=type,
                )
            except Exception:
                pass
        return obj
