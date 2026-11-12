import os
from pathlib import Path
import uuid

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateChatStorage(FileSystemStorage):
    """Store private chat uploads outside the publicly served MEDIA_ROOT."""

    def __init__(self, location=None):
        private_root = location or os.getenv('PRIVATE_CHAT_MEDIA_ROOT') or (
            settings.BASE_DIR / '.private_chat_uploads'
        )
        private_root = Path(private_root).expanduser()
        if not private_root.is_absolute():
            private_root = settings.BASE_DIR / private_root
        resolved_private_root = private_root.resolve()
        resolved_media_root = Path(settings.MEDIA_ROOT).resolve()
        if (
            resolved_private_root == resolved_media_root
            or resolved_media_root in resolved_private_root.parents
        ):
            raise ImproperlyConfigured(
                'PRIVATE_CHAT_MEDIA_ROOT doit rester hors de MEDIA_ROOT.'
            )
        super().__init__(location=resolved_private_root, base_url=None)


def private_message_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()[:12]
    return f'{instance.conversation_id}/{uuid.uuid4().hex}{extension}'
