from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from .storage import PrivateChatStorage, private_message_upload_to

# Délai pendant lequel l'auteur peut corriger son message.
EDIT_WINDOW_SECONDS = 5 * 60


def _reactions_resume(message, user):
    from .reactions import resume
    return resume(message, user)


class ModeratedMessage(models.Model):
    """Champs communs d'édition et de suppression douce des messages."""

    # Dernière modification visible (édition, suppression, épinglage) : sert à
    # transmettre ces changements aux navigateurs déjà ouverts.
    updated_at = models.DateTimeField(default=timezone.now, db_index=True)
    edited_at = models.DateTimeField(null=True, blank=True, verbose_name='Modifié le')
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name='Supprimé le')
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='Supprimé par',
    )

    class Meta:
        abstract = True

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def can_edit(self, user, now=None):
        now = now or timezone.now()
        return (
            not self.is_deleted
            and user is not None
            and self.sender_id == user.pk
            and bool(self.body)
            and not self.is_voice
            and (now - self.created_at).total_seconds() <= EDIT_WINDOW_SECONDS
        )

    def soft_delete(self, by_user):
        now = timezone.now()
        self.deleted_at = now
        self.deleted_by = by_user
        self.updated_at = now
        self.save(update_fields=['deleted_at', 'deleted_by', 'updated_at'])

    def edit_body(self, body):
        now = timezone.now()
        self.body = body
        self.edited_at = now
        self.updated_at = now
        self.save(update_fields=['body', 'edited_at', 'updated_at'])

    def touch(self, *fields):
        self.updated_at = timezone.now()
        self.save(update_fields=[*fields, 'updated_at'])

    def moderation_payload(self, user):
        """Champs d'état communs exposés au navigateur (jamais le contenu supprimé)."""
        return {
            'is_deleted': self.is_deleted,
            'deleted_by_moderator': bool(
                self.is_deleted and self.deleted_by_id and self.deleted_by_id != self.sender_id
            ),
            'is_edited': self.edited_at is not None,
            'can_edit': self.can_edit(user) if user else False,
        }


class ClassChatRoom(models.Model):
    classroom = models.OneToOneField(
        'classrooms.Classroom',
        on_delete=models.CASCADE,
        related_name='chat_room',
        verbose_name='Classe',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(
        default=False,
        verbose_name='Seul le professeur peut écrire',
    )
    allow_student_direct = models.BooleanField(
        default=False,
        verbose_name='Messages privés entre élèves autorisés',
    )
    quiet_hours_start = models.TimeField(
        null=True, blank=True, verbose_name='Début des heures de silence',
    )
    quiet_hours_end = models.TimeField(
        null=True, blank=True, verbose_name='Fin des heures de silence',
    )

    class Meta:
        verbose_name = 'Salon de discussion'
        verbose_name_plural = 'Salons de discussion'

    def __str__(self):
        return f"Chat — {self.classroom.name}"

    @classmethod
    def get_or_create_for(cls, classroom):
        room, _ = cls.objects.get_or_create(classroom=classroom)
        return room

    def in_quiet_hours(self, now=None):
        start, end = self.quiet_hours_start, self.quiet_hours_end
        if not start or not end or start == end:
            return False
        current = timezone.localtime(now or timezone.now()).time()
        if start < end:
            return start <= current < end
        # Plage qui passe minuit, ex. 22:00 → 07:00.
        return current >= start or current < end

    def active_mute_for(self, user, now=None):
        if not user:
            return None
        return self.mutes.filter(user=user, until__gt=now or timezone.now()).first()

    def unread_count_for(self, user):
        if not user or not getattr(user, 'is_authenticated', False):
            return 0
        state = ChatReadState.objects.filter(room=self, user=user).first()
        qs = self.messages.exclude(sender=user).filter(deleted_at__isnull=True)
        if state and state.last_read_at:
            qs = qs.filter(created_at__gt=state.last_read_at)
        return qs.count()

    def last_message(self):
        return self.messages.filter(deleted_at__isnull=True).order_by('-created_at').first()

    def pinned_messages(self):
        return self.messages.filter(
            is_pinned=True, deleted_at__isnull=True,
        ).select_related('sender').order_by('-created_at')

    def mark_read(self, user):
        ChatReadState.objects.update_or_create(
            room=self,
            user=user,
            defaults={'last_read_at': timezone.now()},
        )


class PrivateConversation(models.Model):
    """Conversation privée entre un élève et le professeur de sa classe."""
    classroom = models.ForeignKey(
        'classrooms.Classroom',
        on_delete=models.CASCADE,
        related_name='private_conversations',
        verbose_name='Classe',
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='teacher_conversations',
        verbose_name='Élève',
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='student_conversations',
        verbose_name='Enseignant',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        verbose_name = 'Conversation privée'
        verbose_name_plural = 'Conversations privées'
        constraints = [
            models.UniqueConstraint(
                fields=['classroom', 'student', 'teacher'],
                name='unique_private_chat_class_student_teacher',
            ),
        ]
        ordering = ['-updated_at']

    def __str__(self):
        return f"Consultation — {self.student} / {self.teacher}"

    def last_message(self):
        return self.messages.filter(deleted_at__isnull=True).order_by('-created_at').first()


class PrivateMessage(ModeratedMessage):
    conversation = models.ForeignKey(
        PrivateConversation,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name='Conversation',
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='private_chat_messages',
        verbose_name='Expéditeur',
    )
    body = models.TextField(verbose_name='Message')
    attachment = models.FileField(
        upload_to=private_message_upload_to,
        storage=PrivateChatStorage(),
        blank=True,
        null=True,
        verbose_name='Pièce jointe',
    )
    attachment_name = models.CharField(max_length=255, blank=True)
    is_voice = models.BooleanField(default=False, verbose_name='Message vocal')
    read_at = models.DateTimeField(null=True, blank=True, verbose_name='Lu le')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    # Contexte pédagogique : la leçon ou la question de quiz concernée.
    lesson = models.ForeignKey(
        'education.Lesson',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='Leçon liée',
    )
    question = models.ForeignKey(
        'quizzes.Question',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='Question liée',
    )

    class Meta:
        verbose_name = 'Message privé'
        verbose_name_plural = 'Messages privés'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender}: {(self.body or self.attachment_name)[:40]}"

    @property
    def is_image(self):
        name = self.attachment_name.lower()
        return bool(self.attachment) and any(
            name.endswith(extension)
            for extension in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
        )


class DirectConversation(models.Model):
    """Conversation individuelle entre deux élèves ou un élève et l'administration."""
    participant_one = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='direct_conversations_as_one',
        verbose_name='Premier participant',
    )
    participant_two = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='direct_conversations_as_two',
        verbose_name='Second participant',
    )
    classroom = models.ForeignKey(
        'classrooms.Classroom',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='direct_conversations',
        verbose_name='Classe commune',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        verbose_name = 'Conversation individuelle'
        verbose_name_plural = 'Conversations individuelles'
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['participant_one', 'participant_two'],
                name='unique_direct_conversation_pair',
            ),
            models.CheckConstraint(
                condition=models.Q(participant_one_id__lt=models.F('participant_two_id')),
                name='direct_conversation_canonical_pair',
            ),
        ]

    def __str__(self):
        return f"Conversation — {self.participant_one} / {self.participant_two}"

    @classmethod
    def get_or_create_for(cls, user_a, user_b, classroom=None):
        if user_a.pk == user_b.pk:
            raise ValueError('Une conversation doit avoir deux participants distincts.')
        first, second = sorted((user_a, user_b), key=lambda user: user.pk)
        conversation, created = cls.objects.get_or_create(
            participant_one=first,
            participant_two=second,
            defaults={'classroom': classroom},
        )
        if not created and classroom and conversation.classroom_id != classroom.pk:
            conversation.classroom = classroom
            conversation.save(update_fields=['classroom'])
        return conversation, created

    def other_participant(self, user):
        if user.pk == self.participant_one_id:
            return self.participant_two
        if user.pk == self.participant_two_id:
            return self.participant_one
        if (
            (user.is_staff or user.is_superuser)
            and self.participant_one.is_student() != self.participant_two.is_student()
            and (
                self.participant_one.is_staff
                or self.participant_one.is_superuser
                or self.participant_two.is_staff
                or self.participant_two.is_superuser
            )
        ):
            return (
                self.participant_one
                if self.participant_one.is_student()
                else self.participant_two
            )
        return None

    def last_message(self):
        return self.messages.filter(deleted_at__isnull=True).order_by('-created_at').first()

    def unread_count_for(self, user):
        return self.messages.filter(
            read_at__isnull=True, deleted_at__isnull=True,
        ).exclude(sender=user).count()


class DirectMessage(ModeratedMessage):
    conversation = models.ForeignKey(
        DirectConversation,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name='Conversation',
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='direct_messages',
        verbose_name='Expéditeur',
    )
    body = models.TextField(blank=True, verbose_name='Message')
    attachment = models.FileField(
        upload_to=private_message_upload_to,
        storage=PrivateChatStorage(),
        blank=True,
        null=True,
        verbose_name='Pièce jointe',
    )
    attachment_name = models.CharField(max_length=255, blank=True)
    is_voice = models.BooleanField(default=False, verbose_name='Message vocal')
    read_at = models.DateTimeField(null=True, blank=True, verbose_name='Lu le')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Message individuel'
        verbose_name_plural = 'Messages individuels'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender}: {(self.body or self.attachment_name)[:40]}"

    @property
    def is_image(self):
        name = self.attachment_name.lower()
        return bool(self.attachment) and any(
            name.endswith(extension)
            for extension in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
        )


class ChatPresence(models.Model):
    """Dernière activité vérifiée sur une page de messagerie."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='chat_presence',
    )
    last_seen_at = models.DateTimeField(default=timezone.now, db_index=True)


class ChatMessage(ModeratedMessage):
    room = models.ForeignKey(
        ClassChatRoom,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name='Salon',
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='chat_messages',
        verbose_name='Expéditeur',
    )
    body = models.TextField(blank=True, verbose_name='Message')
    # Stockage privé : les pièces jointes ne passent que par la vue contrôlée.
    # Les anciens fichiers de MEDIA_ROOT/chat restent lisibles (voir attachments.py)
    # jusqu'à l'exécution de `manage.py move_class_chat_attachments`.
    attachment = models.FileField(
        upload_to='chat/%Y/%m/',
        storage=PrivateChatStorage(),
        blank=True,
        null=True,
        verbose_name='Fichier / image',
    )
    whiteboard_share = models.ForeignKey(
        'whiteboard.WhiteboardShare',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chat_messages',
        verbose_name='Tableau partagé',
    )
    reply_to = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replies',
        verbose_name='Réponse à',
    )
    is_pinned = models.BooleanField(default=False, verbose_name='Épinglé')
    is_announcement = models.BooleanField(default=False, verbose_name='Annonce importante')
    is_voice = models.BooleanField(default=False, verbose_name='Message vocal')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Message'
        verbose_name_plural = 'Messages'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender_id}: {(self.body or self.attachment_name)[:40]}"

    @property
    def attachment_name(self):
        if not self.attachment:
            return ''
        return self.attachment.name.rsplit('/', 1)[-1]

    @property
    def is_image(self):
        if not self.attachment:
            return False
        name = self.attachment.name.lower()
        return any(name.endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'))

    def to_dict(self, user=None):
        name = self.sender.get_full_name() or self.sender.username
        deleted = self.is_deleted
        reply = None
        if self.reply_to_id and not deleted:
            r = self.reply_to
            reply = {
                'id': r.pk,
                'body': (
                    'Message supprimé' if r.is_deleted
                    else (r.body or r.attachment_name or 'Message')[:120]
                ),
                'sender_name': r.sender.get_full_name() or r.sender.username,
            }
        share = None
        if self.whiteboard_share_id and not deleted:
            share = {
                'title': self.whiteboard_share.title,
                'image_url': reverse('whiteboard:share_image', args=[self.whiteboard_share_id]),
                'view_url': reverse('whiteboard:share_view', args=[self.whiteboard_share_id]),
            }
        has_attachment = bool(self.attachment) and not deleted
        return {
            'id': self.pk,
            'body': '' if deleted else (self.body or ''),
            'created_at': self.created_at.isoformat(),
            'time_display': timezone.localtime(self.created_at).strftime('%H:%M'),
            'sender_id': self.sender_id,
            'sender_name': name,
            'sender_role': getattr(self.sender, 'role', ''),
            'is_teacher': getattr(self.sender, 'role', '') == 'teacher',
            'attachment_url': (
                reverse('chat:attachment', args=[self.pk]) if has_attachment else ''
            ),
            'attachment_name': self.attachment_name if has_attachment else '',
            'is_image': self.is_image and has_attachment,
            'is_voice': self.is_voice and not deleted,
            'is_pinned': self.is_pinned and not deleted,
            'is_announcement': self.is_announcement and not deleted,
            'reply_to': reply,
            'whiteboard_share': share,
            'reactions': _reactions_resume(self, user),
            **self.moderation_payload(user),
        }


class ChatReadState(models.Model):
    room = models.ForeignKey(
        ClassChatRoom,
        on_delete=models.CASCADE,
        related_name='read_states',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='chat_read_states',
    )
    last_read_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'État de lecture'
        verbose_name_plural = 'États de lecture'
        unique_together = ('room', 'user')


class ChatMute(models.Model):
    """Un élève réduit au silence dans le salon de sa classe jusqu'à `until`."""
    room = models.ForeignKey(ClassChatRoom, on_delete=models.CASCADE, related_name='mutes')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_mutes',
    )
    until = models.DateTimeField(verbose_name='Silence jusqu’au')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Élève en sourdine'
        verbose_name_plural = 'Élèves en sourdine'
        constraints = [
            models.UniqueConstraint(fields=['room', 'user'], name='unique_chat_mute_per_room'),
        ]

    def __str__(self):
        return f'{self.user} muet dans {self.room} jusqu’à {self.until:%d/%m %H:%M}'


class ChatBlock(models.Model):
    """Un élève bloque un camarade : plus aucun message privé entre eux."""
    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_blocks',
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_blocked_by',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Blocage'
        verbose_name_plural = 'Blocages'
        constraints = [
            models.UniqueConstraint(fields=['blocker', 'blocked'], name='unique_chat_block'),
        ]

    @classmethod
    def between(cls, user_a, user_b):
        return cls.objects.filter(
            models.Q(blocker=user_a, blocked=user_b) | models.Q(blocker=user_b, blocked=user_a)
        ).exists()


class ChatReport(models.Model):
    """Signalement d'un message, avec un instantané conservé pour l'examen."""
    KIND_CLASS = 'class'
    KIND_CONSULTATION = 'consultation'
    KIND_DIRECT = 'direct'
    KIND_CHOICES = [
        (KIND_CLASS, 'Salon de classe'),
        (KIND_CONSULTATION, 'Consultation'),
        (KIND_DIRECT, 'Message individuel'),
    ]
    REASON_CHOICES = [
        ('harassment', 'Harcèlement ou insulte'),
        ('inappropriate', 'Contenu inapproprié'),
        ('spam', 'Spam ou hors sujet'),
        ('cheating', 'Triche (réponses de quiz)'),
        ('other', 'Autre'),
    ]
    STATUS_OPEN = 'open'
    STATUS_CHOICES = [
        (STATUS_OPEN, 'À traiter'),
        ('resolved', 'Traité'),
        ('dismissed', 'Classé sans suite'),
    ]

    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    message_id = models.PositiveBigIntegerField()
    classroom = models.ForeignKey(
        'classrooms.Classroom', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='chat_reports',
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_reports_sent',
    )
    reported_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='chat_reports_received',
    )
    reason = models.CharField(max_length=20, choices=REASON_CHOICES)
    details = models.TextField(blank=True, max_length=1000)
    # Le message signalé et quelques messages précédents, figés au moment du
    # signalement : l'examinateur n'a pas besoin de lire toute la conversation.
    snapshot = models.JSONField(default=list)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    handled_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Signalement'
        verbose_name_plural = 'Signalements'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['kind', 'message_id', 'reporter'], name='unique_chat_report_per_reporter',
            ),
        ]

    def __str__(self):
        return f'Signalement {self.get_kind_display()} #{self.message_id}'


class MessageReaction(models.Model):
    """Réaction d'un utilisateur à un message (une seule par personne et par message)."""
    EMOJIS = ('👍', '❤️', '😂', '😮', '✅', '❓')
    LABELS = {
        '👍': 'J’aime', '❤️': 'J’adore', '😂': 'Drôle', '😮': 'Surprenant',
        '✅': 'Compris', '❓': 'Pas compris',
    }

    kind = models.CharField(max_length=20, choices=ChatReport.KIND_CHOICES)
    message_id = models.PositiveBigIntegerField()
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_reactions',
    )
    emoji = models.CharField(max_length=8)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Réaction'
        verbose_name_plural = 'Réactions'
        constraints = [
            models.UniqueConstraint(
                fields=['kind', 'message_id', 'user'], name='unique_chat_reaction_per_user',
            ),
        ]
        indexes = [models.Index(fields=['kind', 'message_id'], name='chat_reaction_message_idx')]

    def __str__(self):
        return f'{self.emoji} {self.get_kind_display()} #{self.message_id}'
