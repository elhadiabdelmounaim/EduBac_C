"""Images du tableau mathématique : fichiers dans MEDIA_ROOT/mathboard/<document>/,
servis par Django avec contrôle d'accès (jamais par une correspondance /media/
publique, qui n'existe pas en production sur PythonAnywhere).

Adresse d'une image : /tableau-maths/<document>/images/<32 hex>.<png|jpg|webp>
Les anciennes adresses /media/mathboard/… restent reconnues (nettoyage, conversion).
"""
import re
import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.urls import reverse

FILENAME = re.compile(r'^[0-9a-f]{32}\.(png|jpg|webp)$')
CONTENT_TYPES = {'png': 'image/png', 'jpg': 'image/jpeg', 'webp': 'image/webp'}
# Fichier référencé dans le contenu (nouvelle ou ancienne adresse).
REFERENCE = re.compile(r'/(?:tableau-maths/(\d+)/images|media/mathboard/(\d+))/([0-9a-f]{32}\.(?:png|jpg|webp))')


def image_url(document_id, filename):
    return reverse('mathboard:image', args=[document_id, filename])


def save_image(document_id, data, extension):
    """Enregistre les octets d'une image et renvoie son adresse."""
    name = default_storage.save(f'mathboard/{document_id}/{uuid.uuid4().hex}.{extension}', ContentFile(data))
    return image_url(document_id, name.rsplit('/', 1)[-1])


def storage_name(src):
    """Nom dans le stockage d'une image référencée par `src`, ou None."""
    match = REFERENCE.search(str(src or ''))
    if not match or not str(src).startswith('/'):
        return None
    return f'mathboard/{match.group(1) or match.group(2)}/{match.group(3)}'


def referenced_names(text):
    """Tous les fichiers d'images cités dans un texte (JSON sérialisé)."""
    return {f'mathboard/{a or b}/{f}' for a, b, f in REFERENCE.findall(text)}
