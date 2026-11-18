from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from . import catalog


class Notification(models.Model):
    """
    Notification utilisateur EduBac.

    Une notification peut être « regroupée » (group_key) : tant qu'elle n'est pas
    lue, les nouveaux événements du même groupe la mettent à jour au lieu d'en
    créer une autre (ex. « 12 élèves ont terminé le quiz »).
    """
    TYPE_CHOICES = catalog.TYPE_CHOICES

    EMAIL_NONE = ''
    EMAIL_DIGEST = 'digest'
    EMAIL_SENT = 'sent'
    EMAIL_STATUS_CHOICES = [
        (EMAIL_NONE, 'Aucun'),
        (EMAIL_DIGEST, 'En attente du résumé'),
        (EMAIL_SENT, 'Envoyé'),
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
    updated_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name='Mise à jour le')
    group_key = models.CharField(max_length=120, blank=True, db_index=True)
    count = models.PositiveIntegerField(default=1, verbose_name='Événements regroupés')
    email_status = models.CharField(
        max_length=10, blank=True, choices=EMAIL_STATUS_CHOICES, db_index=True,
    )

    class Meta:
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'
        ordering = ['-updated_at', '-pk']
        indexes = [
            models.Index(fields=['recipient', 'is_read', '-created_at']),
            models.Index(fields=['recipient', '-updated_at']),
        ]

    def __str__(self):
        status = '✓' if self.is_read else '●'
        return f"{status} {self.title} → {self.recipient.username}"

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=['is_read'])

    @property
    def icon(self):
        return catalog.icon_for(self.type)

    @property
    def safe_link(self):
        """Lien interne uniquement (jamais vers un autre site)."""
        link = self.link or ''
        return link if link.startswith('/') and not link.startswith('//') else ''

    @property
    def time_ago(self):
        """Texte relatif simple en français."""
        delta = timezone.now() - self.updated_at
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
        return timezone.localtime(self.updated_at).strftime('%d/%m/%Y')

    @classmethod
    def notify(cls, recipient, title, message, type='system', actor=None, link='',
               send_email=True, group_key='', defer_email=False):
        """Crée (ou met à jour, si regroupée) une notification et gère l'e-mail.

        `send_email` indique que l'événement mérite un e-mail ; c'est la
        préférence du destinataire qui décide ensuite : immédiat, résumé
        quotidien ou jamais. `defer_email` reporte un envoi immédiat au résumé
        quotidien : la requête en cours (ex. une inscription) n'attend pas SMTP.
        """
        preference = NotificationPreference.for_user(recipient, type)
        email_mode = preference['email'] if send_email else catalog.EMAIL_OFF
        if defer_email and email_mode == catalog.EMAIL_INSTANT:
            email_mode = catalog.EMAIL_DIGEST
        now = timezone.now()

        obj = None
        if group_key:
            with transaction.atomic():
                obj = (
                    cls.objects.select_for_update()
                    .filter(recipient=recipient, group_key=group_key, is_read=False)
                    .order_by('-updated_at')
                    .first()
                )
                if obj is not None:
                    obj.title = title
                    obj.message = message
                    obj.actor = actor
                    obj.link = link or ''
                    obj.updated_at = now
                    obj.count += 1
                    fields = ['title', 'message', 'actor', 'link', 'updated_at', 'count']
                    if email_mode == catalog.EMAIL_DIGEST and obj.email_status != cls.EMAIL_DIGEST:
                        obj.email_status = cls.EMAIL_DIGEST
                        fields.append('email_status')
                    obj.save(update_fields=fields)
                    # Pas de nouvel e-mail immédiat pour un même groupe déjà signalé,
                    # mais le téléphone est prévenu (la notification du groupe est remplacée).
                    cls._push(recipient.pk, title, message, link, group_key)
                    return obj

        obj = cls.objects.create(
            recipient=recipient,
            actor=actor,
            type=type,
            title=title,
            message=message,
            link=link or '',
            group_key=group_key or '',
            updated_at=now,
            is_read=not preference['in_app'],
            email_status=cls.EMAIL_DIGEST if email_mode == catalog.EMAIL_DIGEST else cls.EMAIL_NONE,
        )
        if preference['in_app']:
            cls._push(recipient.pk, title, message, link, group_key or f'notif-{obj.pk}')
        if email_mode == catalog.EMAIL_INSTANT:
            try:
                from .email_utils import send_notification_email
                if send_notification_email(
                    recipient=recipient,
                    title=title,
                    message=message,
                    link=link or '',
                    type_code=type,
                ):
                    obj.email_status = cls.EMAIL_SENT
                    obj.save(update_fields=['email_status'])
            except Exception:
                pass
        return obj

    @classmethod
    def notify_many(cls, recipients, title, message, type='system', actor=None, link='', group_key=''):
        """Notification in-app pour beaucoup de destinataires en une requête (pas d'e-mail)."""
        recipients = list(recipients)
        if not recipients:
            return 0
        muted = NotificationPreference.muted_user_ids(recipients, type)
        now = timezone.now()
        cls.objects.bulk_create([
            cls(
                recipient=user,
                actor=actor,
                type=type,
                title=title,
                message=message,
                link=link or '',
                group_key=group_key or '',
                created_at=now,
                updated_at=now,
                is_read=user.pk in muted,
            )
            for user in recipients
        ])
        cls._push([user.pk for user in recipients if user.pk not in muted], title, message, link,
                  group_key or f'many-{int(now.timestamp())}')
        return len(recipients)

    @staticmethod
    def _push(user_ids, title, message, link, tag):
        """Notification sur les téléphones abonnés (Web Push), sans bloquer."""
        try:
            from .push import push_to_users
            ids = user_ids if isinstance(user_ids, (list, tuple, set)) else [user_ids]
            push_to_users(ids, title, message, url=link or '/notifications/', tag=tag)
        except Exception:
            pass

    @classmethod
    def mark_group_read(cls, recipient, group_key):
        return cls.objects.filter(
            recipient=recipient, group_key=group_key, is_read=False,
        ).update(is_read=True)


class NotificationPreference(models.Model):
    """Choix de l'utilisateur, type par type : {type: {'in_app': bool, 'email': mode}}."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_preference',
    )
    values = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Préférences de notification'
        verbose_name_plural = 'Préférences de notification'

    @classmethod
    def for_user(cls, user, type_code):
        preference = catalog.default_preference(user, type_code)
        stored = cls.objects.filter(user=user).values_list('values', flat=True).first() or {}
        chosen = stored.get(type_code) or {}
        if isinstance(chosen.get('in_app'), bool):
            preference['in_app'] = chosen['in_app']
        if chosen.get('email') in dict(catalog.EMAIL_CHOICES):
            preference['email'] = chosen['email']
        return preference

    @classmethod
    def all_for_user(cls, user):
        return {code: cls.for_user(user, code) for code in catalog.types_for(user)}

    @classmethod
    def muted_user_ids(cls, users, type_code):
        """Utilisateurs ayant désactivé ce type « dans EduBac »."""
        ids = {user.pk for user in users}
        muted = set()
        for user_id, values in cls.objects.filter(user_id__in=ids).values_list('user_id', 'values'):
            if (values or {}).get(type_code, {}).get('in_app') is False:
                muted.add(user_id)
        return muted


class PushSubscription(models.Model):
    """Appareil (téléphone, ordinateur) abonné aux notifications Web Push d'un utilisateur."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='push_subscriptions',
    )
    endpoint = models.URLField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    failures = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = 'Abonnement aux notifications du téléphone'
        verbose_name_plural = 'Abonnements aux notifications du téléphone'

    def __str__(self):
        return f'{self.user} — {self.user_agent[:40] or self.endpoint[:40]}'
