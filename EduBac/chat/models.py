from django.conf import settings
from django.db import models
from django.utils import timezone


class ClassChatRoom(models.Model):
    classroom = models.OneToOneField(
        'classrooms.Classroom',
        on_delete=models.CASCADE,
        related_name='chat_room',
        verbose_name='Classe',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Salon de discussion'
        verbose_name_plural = 'Salons de discussion'

    def __str__(self):
        return f"Chat — {self.classroom.name}"

    @classmethod
    def get_or_create_for(cls, classroom):
        room, _ = cls.objects.get_or_create(classroom=classroom)
        return room

    def unread_count_for(self, user):
        if not user or not getattr(user, 'is_authenticated', False):
            return 0
        state = ChatReadState.objects.filter(room=self, user=user).first()
        qs = self.messages.exclude(sender=user)
        if state and state.last_read_at:
            qs = qs.filter(created_at__gt=state.last_read_at)
        return qs.count()

    def last_message(self):
        return self.messages.order_by('-created_at').first()

    def pinned_messages(self):
        return self.messages.filter(is_pinned=True).select_related('sender').order_by('-created_at')

    def mark_read(self, user):
        ChatReadState.objects.update_or_create(
            room=self,
            user=user,
            defaults={'last_read_at': timezone.now()},
        )


class ChatMessage(models.Model):
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
    attachment = models.FileField(
        upload_to='chat/%Y/%m/',
        blank=True,
        null=True,
        verbose_name='Fichier / image',
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

    def to_dict(self):
        name = self.sender.get_full_name() or self.sender.username
        reply = None
        if self.reply_to_id:
            r = self.reply_to
            reply = {
                'id': r.pk,
                'body': (r.body or r.attachment_name or 'Message')[:120],
                'sender_name': r.sender.get_full_name() or r.sender.username,
            }
        return {
            'id': self.pk,
            'body': self.body or '',
            'created_at': self.created_at.isoformat(),
            'time_display': self.created_at.strftime('%H:%M'),
            'sender_id': self.sender_id,
            'sender_name': name,
            'sender_role': getattr(self.sender, 'role', ''),
            'is_teacher': getattr(self.sender, 'role', '') == 'teacher',
            'attachment_url': self.attachment.url if self.attachment else '',
            'attachment_name': self.attachment_name,
            'is_image': self.is_image,
            'is_voice': self.is_voice,
            'is_pinned': self.is_pinned,
            'reply_to': reply,
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
