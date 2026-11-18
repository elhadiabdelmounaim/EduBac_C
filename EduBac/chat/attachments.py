"""Validation et diffusion des pièces jointes, communes aux trois messageries.

Une seule implémentation pour le salon de classe, les consultations et les
messages individuels : extension autorisée, signature réelle du fichier
(magic bytes), taille, puis diffusion sans exécution possible dans le navigateur.
"""
import mimetypes
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
AUDIO_EXTENSIONS = {'.webm', '.ogg', '.mp3', '.wav', '.m4a', '.aac'}
DOCUMENT_EXTENSIONS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt', '.zip'}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | AUDIO_EXTENSIONS | DOCUMENT_EXTENSIONS

# Types servis en ligne. Jamais text/html ni image/svg+xml, exécutables par le navigateur.
INLINE_CONTENT_TYPES = {
    'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/bmp',
    'video/webm',  # enregistrements vocaux WebM
}

_OLE = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'  # .doc / .xls
_ZIP = (b'PK\x03\x04', b'PK\x05\x06')        # .zip / .docx / .xlsx


def _riff(head, form):
    return head[:4] == b'RIFF' and head[8:12] == form


def _mp3(head):
    return head[:3] == b'ID3' or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0)


def _aac(head):
    return len(head) > 1 and head[0] == 0xFF and head[1] & 0xF6 == 0xF0


def _mp4(head):
    return head[4:8] == b'ftyp'


def _text(head):
    return b'\x00' not in head


SIGNATURES = {
    '.jpg': lambda h: h[:3] == b'\xff\xd8\xff',
    '.jpeg': lambda h: h[:3] == b'\xff\xd8\xff',
    '.png': lambda h: h[:8] == b'\x89PNG\r\n\x1a\n',
    '.gif': lambda h: h[:6] in (b'GIF87a', b'GIF89a'),
    '.webp': lambda h: _riff(h, b'WEBP'),
    '.bmp': lambda h: h[:2] == b'BM',
    '.pdf': lambda h: h[:5] == b'%PDF-',
    '.zip': lambda h: h[:4] in _ZIP,
    '.docx': lambda h: h[:4] in _ZIP,
    '.xlsx': lambda h: h[:4] in _ZIP,
    '.doc': lambda h: h[:8] == _OLE,
    '.xls': lambda h: h[:8] == _OLE,
    '.txt': _text,
    '.webm': lambda h: h[:4] == b'\x1a\x45\xdf\xa3',
    '.ogg': lambda h: h[:4] == b'OggS',
    '.wav': lambda h: _riff(h, b'WAVE'),
    '.mp3': _mp3,
    '.m4a': _mp4,
    # Safari enregistre en AAC dans un conteneur MP4 : accepter les deux formes.
    '.aac': lambda h: _aac(h) or _mp4(h),
}


class AttachmentError(ValueError):
    """Pièce jointe refusée ; le message est destiné à l'utilisateur."""


def validate_upload(upload, *, is_voice=False):
    """Valide un fichier téléversé et retourne (nom_affiché, is_voice).

    Lève AttachmentError si le fichier est trop gros, d'un type non autorisé,
    ou si son contenu ne correspond pas à son extension.
    """
    if upload.size > MAX_UPLOAD_BYTES:
        raise AttachmentError('Fichier trop volumineux (maximum 10 Mo).')
    original_name = (upload.name or '').replace('\\', '/')
    display_name = Path(original_name).name[:255]
    extension = Path(display_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise AttachmentError('Type de fichier non autorisé.')
    if is_voice and extension not in AUDIO_EXTENSIONS:
        raise AttachmentError('Un message vocal doit être un fichier audio.')
    position = upload.tell() if hasattr(upload, 'tell') else 0
    head = upload.read(4096)
    upload.seek(position)
    if not head or not SIGNATURES[extension](head):
        raise AttachmentError(
            'Le contenu du fichier ne correspond pas à son type. '
            'Enregistrez-le de nouveau puis réessayez.'
        )
    return display_name, extension in AUDIO_EXTENSIONS


def is_image_name(name):
    return Path(name or '').suffix.lower() in IMAGE_EXTENSIONS


def _open_legacy_class_file(name):
    """Anciennes pièces jointes du salon de classe, encore dans MEDIA_ROOT/chat."""
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts or relative.parts[:1] != ('chat',):
        raise FileNotFoundError(name)
    root = Path(settings.MEDIA_ROOT).resolve()
    candidate = (root / relative)
    if candidate.is_symlink():
        raise FileNotFoundError(name)
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise FileNotFoundError(name)
    return resolved.open('rb')


def serve_attachment(field_file, display_name, *, legacy_media_fallback=False):
    """Réponse de téléchargement sûre pour une pièce jointe de messagerie."""
    if not field_file:
        raise Http404
    try:
        handle = field_file.open('rb')
    except FileNotFoundError:
        if not legacy_media_fallback:
            raise Http404
        try:
            handle = _open_legacy_class_file(field_file.name)
        except (FileNotFoundError, OSError):
            raise Http404
    filename = display_name or Path(field_file.name).name or 'piece-jointe'
    content_type = mimetypes.guess_type(filename)[0]
    inline = content_type in INLINE_CONTENT_TYPES or (
        bool(content_type) and content_type.startswith('audio/')
    )
    response = FileResponse(
        handle,
        content_type=content_type or 'application/octet-stream',
        as_attachment=not inline,
        filename=filename,
    )
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response
