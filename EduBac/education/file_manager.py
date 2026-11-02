"""Safe file placement for lesson resources managed through Django Admin."""

import hashlib
import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils.text import slugify
from PIL import Image, UnidentifiedImageError

from .media_library import chapter_relative
from .models import Resources

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024

CATEGORY_CONFIG = {
    'course_pdf': {
        'label': 'Cours — PDF',
        'folder': 'Cours',
        'extensions': ('.pdf',),
    },
    'course_markdown': {
        'label': 'Cours — Markdown + LaTeX',
        'folder': 'Cours',
        'extensions': ('.md',),
    },
    'summary_pdf': {
        'label': 'Résumé — PDF',
        'folder': 'Cours',
        'prefix': 'resume',
        'extensions': ('.pdf',),
    },
    'exercise_pdf': {
        'label': 'Exercices — PDF',
        'folder': 'Exercices',
        'prefix': 'exercices',
        'extensions': ('.pdf',),
    },
    'series_pdf': {
        'label': 'Série d’exercices — PDF',
        'folder': 'Exercices',
        'prefix': 'serie-exercices',
        'extensions': ('.pdf',),
    },
    'exam_pdf': {
        'label': 'Devoir surveillé — PDF',
        'folder': 'Exercices',
        'prefix': 'devoir-surveille',
        'extensions': ('.pdf',),
    },
    'correction_pdf': {
        'label': 'Correction — PDF',
        'folder': 'Exercices',
        'prefix': 'correction',
        'extensions': ('.pdf',),
    },
    'ai_source': {
        'label': 'Source pédagogique pour l’IA — TXT',
        'folder': 'Sources_IA',
        'extensions': ('.txt',),
    },
    'image': {
        'label': 'Image pédagogique',
        'folder': None,
        'extensions': ('.jpg', '.jpeg', '.png', '.gif', '.webp'),
        'resource_type': 'image',
    },
    'document': {
        'label': 'Autre document pédagogique',
        'folder': None,
        'extensions': (
            '.pdf', '.docx', '.xlsx', '.pptx', '.txt', '.csv',
        ),
        'resource_type': 'doc',
    },
}


class FileManagerError(Exception):
    """A safe, user-facing error from the lesson file manager."""


def category_choices():
    return [(key, value['label']) for key, value in CATEGORY_CONFIG.items()]


def _media_root():
    return Path(settings.MEDIA_ROOT).expanduser().resolve()


def _media_path(relative_path):
    relative = Path(relative_path)
    if relative.is_absolute() or '..' in relative.parts:
        raise FileManagerError('Le chemin de destination est invalide.')
    root = _media_root()
    candidate = root / relative
    if not candidate.parent.resolve().is_relative_to(root):
        raise FileManagerError('Le chemin de destination sort du dossier MEDIA.')
    if candidate.is_symlink():
        raise FileManagerError('Un lien symbolique bloque cette destination.')
    if candidate.exists() and not candidate.resolve().is_relative_to(root):
        raise FileManagerError('Le fichier de destination sort du dossier MEDIA.')
    return candidate


def _is_resource_path(relative_path):
    relative = Path(relative_path)
    return (
        not relative.is_absolute()
        and len(relative.parts) >= 2
        and relative.parts[0] == 'resources'
        and '..' not in relative.parts
    )


def _resource_type(category, extension):
    if category == 'image':
        return 'image'
    return 'pdf' if extension == '.pdf' else 'doc'


def _safe_stem(title):
    return (slugify(title)[:140].strip('-') or 'document')


def destination_for(lesson, category, title, extension):
    config = CATEGORY_CONFIG.get(category)
    extension = extension.lower()
    if not config or extension not in config['extensions']:
        raise FileManagerError('Cette catégorie n’accepte pas ce format de fichier.')

    stem = _safe_stem(title)
    prefix = config.get('prefix')
    if prefix:
        stem = f'{prefix}-{stem}'

    if config['folder'] is None:
        relative = Path('resources') / f'lesson-{lesson.pk}-{stem}{extension}'
    else:
        relative = chapter_relative(lesson) / config['folder'] / f'{stem}{extension}'
    return relative.as_posix()


def replacement_destination(lesson, category, selection, extension):
    """Resolve a replacement only from files listed for this lesson/category."""
    config = CATEGORY_CONFIG.get(category)
    if not config or not selection:
        raise FileManagerError('Sélectionnez un fichier existant à remplacer.')

    if config['folder'] is None:
        if not selection.startswith('resource:'):
            raise FileManagerError('La ressource à remplacer n’est plus disponible.')
        try:
            resource_id = int(selection.split(':', 1)[1])
            resource = Resources.objects.get(pk=resource_id, lesson=lesson)
        except (ValueError, Resources.DoesNotExist) as exc:
            raise FileManagerError('La ressource à remplacer n’existe plus.') from exc
        if category == 'image' and resource.type != 'image':
            raise FileManagerError('La ressource sélectionnée n’est pas une image.')
        if category == 'document' and resource.type == 'image':
            raise FileManagerError('La ressource sélectionnée est une image.')
        relative_path = resource.file.name
        if not _is_resource_path(relative_path):
            raise FileManagerError('Cette ressource n’est pas stockée dans le dossier pédagogique autorisé.')
    else:
        if not selection.startswith('file:'):
            raise FileManagerError('Le fichier à remplacer n’est plus disponible.')
        filename = selection.split(':', 1)[1]
        if Path(filename).name != filename:
            raise FileManagerError('Le nom du fichier à remplacer est invalide.')
        available_names = {
            item['filename'] for item in existing_items(lesson, category)
        }
        if filename not in available_names:
            raise FileManagerError('Le fichier sélectionné n’existe plus dans cette catégorie.')
        relative_path = (
            chapter_relative(lesson) / config['folder'] / filename
        ).as_posix()

    target = _media_path(relative_path)
    if Path(relative_path).suffix.lower() != extension:
        raise FileManagerError(
            'Pour remplacer ce fichier, utilisez le même format que le fichier sélectionné.'
        )
    if not target.is_file():
        raise FileManagerError('Le fichier sélectionné n’existe plus.')
    return relative_path


def _read_prefix(upload, size=4096):
    upload.seek(0)
    content = upload.read(size)
    upload.seek(0)
    return content


def validate_upload(upload, category):
    config = CATEGORY_CONFIG.get(category)
    if not config:
        raise FileManagerError('Sélectionnez une catégorie reconnue.')
    extension = Path(upload.name or '').suffix.lower()
    if extension not in config['extensions']:
        allowed = ', '.join(config['extensions'])
        raise FileManagerError(f'Format non autorisé pour cette catégorie. Formats acceptés : {allowed}.')
    if upload.size <= 0:
        raise FileManagerError('Le fichier est vide.')
    if upload.size > MAX_UPLOAD_BYTES:
        raise FileManagerError('Le fichier dépasse la limite de 20 Mo.')

    try:
        prefix = _read_prefix(upload)
        if extension == '.pdf':
            if b'%PDF-' not in prefix[:1024]:
                raise FileManagerError('Le fichier ne semble pas être un PDF valide.')
        elif extension in {'.txt', '.md', '.csv'}:
            upload.seek(0)
            try:
                text = upload.read().decode('utf-8-sig')
            except UnicodeDecodeError as exc:
                raise FileManagerError('Le fichier texte doit être encodé en UTF-8.') from exc
            if not text.strip():
                raise FileManagerError('Le fichier texte est vide.')
        elif extension in {'.jpg', '.jpeg', '.png', '.gif', '.webp'}:
            upload.seek(0)
            with Image.open(upload) as image:
                image.verify()
                expected = {
                    '.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG',
                    '.gif': 'GIF', '.webp': 'WEBP',
                }[extension]
                if image.format != expected:
                    raise FileManagerError('L’extension ne correspond pas au contenu de l’image.')
        elif extension in {'.docx', '.xlsx', '.pptx'}:
            expected_part = {
                '.docx': 'word/document.xml',
                '.xlsx': 'xl/workbook.xml',
                '.pptx': 'ppt/presentation.xml',
            }[extension]
            upload.seek(0)
            with zipfile.ZipFile(upload) as package:
                names = set(package.namelist())
                if '[Content_Types].xml' not in names or expected_part not in names:
                    raise FileManagerError('Le document Office ne semble pas valide.')
    except FileManagerError:
        raise
    except (
        OSError,
        ValueError,
        zipfile.BadZipFile,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ) as exc:
        raise FileManagerError('Le fichier est illisible ou son format est invalide.') from exc
    finally:
        upload.seek(0)
    return extension


def _hash_upload(upload):
    digest = hashlib.sha256()
    upload.seek(0)
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()


def _hash_path(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _category_directory(lesson, category):
    config = CATEGORY_CONFIG[category]
    if config['folder'] is None:
        return _media_path('resources')
    return _media_path(chapter_relative(lesson) / config['folder'])


def _matching_existing_file(lesson, category, extension, digest):
    config = CATEGORY_CONFIG[category]
    if config['folder'] is None:
        resources = Resources.objects.filter(lesson=lesson).order_by('pk')
        expected_type = _resource_type(category, extension)
        for resource in resources:
            if resource.type != expected_type or not resource.file:
                continue
            if not _is_resource_path(resource.file.name):
                continue
            try:
                path = _media_path(resource.file.name)
                if path.is_file():
                    try:
                        if _hash_path(path) == digest:
                            return path.relative_to(_media_root()).as_posix()
                    except OSError:
                        continue
            except (OSError, FileManagerError):
                continue
        return None

    folder = _category_directory(lesson, category)
    if not folder.is_dir():
        return None
    for path in sorted(folder.iterdir(), key=lambda item: item.name.casefold()):
        if (
            path.suffix.lower() == extension
            and not path.is_symlink()
            and path.is_file()
        ):
            try:
                if _hash_path(path) == digest:
                    return path.relative_to(_media_root()).as_posix()
            except OSError:
                continue
    return None


def _save_resource_record(lesson, relative_path, title, resource_type):
    existing = Resources.objects.select_for_update().filter(file=relative_path).first()
    if existing and existing.lesson_id != lesson.pk:
        raise FileManagerError('Cette ressource est déjà associée à une autre leçon.')
    if existing:
        existing.name = title
        existing.type = resource_type
        existing.lesson = lesson
        existing.save(update_fields=('name', 'type', 'lesson'))
        return existing
    return Resources.objects.create(
        name=title,
        type=resource_type,
        lesson=lesson,
        file=relative_path,
    )


def _write_uploaded_file(upload, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.parent.resolve().is_relative_to(_media_root()):
        raise FileManagerError('Le dossier de destination sort de MEDIA_ROOT.')

    backup = None
    temp_name = None
    try:
        descriptor, temp_name = tempfile.mkstemp(
            prefix='.edubac-import-', dir=target.parent
        )
        with os.fdopen(descriptor, 'wb') as destination:
            upload.seek(0)
            for chunk in upload.chunks():
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        if target.exists():
            if target.is_symlink() or not target.is_file():
                raise FileManagerError('La destination existante n’est pas un fichier ordinaire.')
            descriptor, backup_name = tempfile.mkstemp(
                prefix='.edubac-backup-', dir=target.parent
            )
            os.close(descriptor)
            backup = Path(backup_name)
            shutil.copy2(target, backup)
        os.replace(temp_name, target)
        temp_name = None
        return backup
    except Exception:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
        if backup and backup.exists():
            backup.unlink()
        raise


def save_upload(
    lesson,
    category,
    title,
    upload,
    *,
    confirm_replace,
    replacement_selection='',
):
    extension = validate_upload(upload, category)
    relative_path = (
        replacement_destination(
            lesson, category, replacement_selection, extension
        )
        if replacement_selection
        else destination_for(lesson, category, title, extension)
    )
    target = _media_path(relative_path)
    digest = _hash_upload(upload)

    if category == 'course_markdown':
        folder = _category_directory(lesson, category)
        if folder.is_dir():
            other_markdown = [
                path for path in folder.iterdir()
                if path.suffix.lower() == '.md'
                and path.name != target.name
                and not path.is_symlink()
                and path.is_file()
            ]
            if other_markdown:
                raise FileManagerError(
                    'Cette leçon possède déjà un autre fichier Markdown. '
                    'Utilisez son nom actuel pour le remplacer sans créer de doublon.'
                )

    same_content = _matching_existing_file(
        lesson, category, extension, digest
    )
    if target.is_file() and not target.is_symlink():
        try:
            if _hash_path(target) == digest:
                same_content = relative_path
        except OSError as exc:
            raise FileManagerError(
                'Le fichier de destination ne peut pas être lu; il n’a pas été modifié.'
            ) from exc
    if same_content and same_content != relative_path:
        return {'status': 'duplicate', 'path': same_content}
    if (
        same_content == relative_path
        and not replacement_selection
        and CATEGORY_CONFIG[category]['folder'] is None
    ):
        with transaction.atomic():
            _save_resource_record(
                lesson,
                relative_path,
                title,
                _resource_type(category, extension),
            )
        return {'status': 'duplicate', 'path': relative_path}

    target_exists = target.exists()
    if target_exists and not confirm_replace:
        raise FileManagerError(
            'Un fichier existe déjà. Sélectionnez-le puis confirmez son remplacement.'
        )
    if target_exists and not replacement_selection:
        raise FileManagerError(
            'Sélectionnez précisément le fichier existant dans la liste avant de le remplacer.'
        )
    if target_exists and target.is_symlink():
        raise FileManagerError('La destination existante est un lien symbolique; elle n’a pas été modifiée.')

    if CATEGORY_CONFIG[category]['folder'] is None:
        other_reference = Resources.objects.filter(file=relative_path).exclude(
            lesson=lesson
        ).exists()
        if other_reference:
            raise FileManagerError(
                'Cette destination est déjà utilisée par une autre leçon.'
            )

    backup = None
    created_target = not target_exists
    try:
        if not (target_exists and same_content == relative_path):
            backup = _write_uploaded_file(upload, target)
        if CATEGORY_CONFIG[category]['folder'] is None:
            with transaction.atomic():
                _save_resource_record(
                    lesson,
                    relative_path,
                    title,
                    _resource_type(category, extension),
                )
    except Exception as exc:
        try:
            if backup and backup.exists():
                os.replace(backup, target)
            elif created_target and target.exists():
                target.unlink()
        except OSError:
            logger.exception('Failed to restore a file after a resource import error')
        if isinstance(exc, FileManagerError):
            raise
        logger.exception('Lesson resource import failed')
        raise FileManagerError(
            'L’importation a échoué. Le fichier précédent a été conservé.'
        ) from exc
    finally:
        upload.seek(0)

    if backup and backup.exists():
        try:
            backup.unlink()
        except OSError:
            logger.exception('Could not remove a temporary file-manager backup')
    return {
        'status': 'replaced' if target_exists else 'created',
        'path': relative_path,
    }


def existing_items(lesson, category):
    config = CATEGORY_CONFIG.get(category)
    if not config:
        return []
    if config['folder'] is None:
        expected_type = 'image' if category == 'image' else None
        resources = Resources.objects.filter(lesson=lesson).order_by('name', 'pk')
        if expected_type:
            resources = resources.filter(type=expected_type)
        else:
            resources = resources.exclude(type='image')
        items = []
        for resource in resources:
            if not resource.file:
                continue
            if not _is_resource_path(resource.file.name):
                continue
            try:
                path = _media_path(resource.file.name)
            except FileManagerError:
                continue
            if path.is_file():
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                items.append({
                    'name': resource.name,
                    'filename': path.name,
                    'size': size,
                    'resource_id': resource.pk,
                    'relative_path': resource.file.name,
                })
        return items

    folder = _category_directory(lesson, category)
    if not folder.is_dir():
        return []
    items = []
    for path in sorted(folder.iterdir(), key=lambda item: item.name.casefold()):
        if (
            path.suffix.lower() not in config['extensions']
            or path.is_symlink()
            or not path.is_file()
        ):
            continue
        if not path.resolve().is_relative_to(_media_root()):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        items.append({
            'name': path.name,
            'filename': path.name,
            'size': size,
            'resource_id': None,
            'relative_path': path.relative_to(_media_root()).as_posix(),
        })
    return items


def delete_managed_file(
    lesson, category, *, filename='', resource_id=None, admin_user_id=None
):
    config = CATEGORY_CONFIG.get(category)
    if not config:
        raise FileManagerError('Sélectionnez une catégorie reconnue.')
    if config['folder'] is None:
        try:
            resource = Resources.objects.get(
                pk=resource_id,
                lesson=lesson,
            )
        except Resources.DoesNotExist as exc:
            raise FileManagerError('Cette ressource n’existe plus pour cette leçon.') from exc
        if category == 'image' and resource.type != 'image':
            raise FileManagerError('Cette ressource n’est pas une image.')
        if category == 'document' and resource.type == 'image':
            raise FileManagerError('Cette ressource est une image.')
        relative_path = resource.file.name
        if not _is_resource_path(relative_path):
            raise FileManagerError(
                'Ce fichier n’est pas dans le dossier des ressources pédagogiques.'
            )
        if Resources.objects.filter(file=relative_path).exclude(pk=resource.pk).exists():
            raise FileManagerError(
                'Le fichier est partagé avec une autre ressource; il n’a pas été supprimé.'
            )
        try:
            path = _media_path(relative_path)
        except FileManagerError as exc:
            raise FileManagerError('Le chemin de cette ressource n’est pas autorisé.') from exc
        if not path.is_file():
            raise FileManagerError('Le fichier est déjà absent.')
        resource.delete()
        logger.warning(
            'Admin user %s deleted lesson resource %s',
            admin_user_id,
            relative_path,
        )
        return relative_path

    if not filename or Path(filename).name != filename:
        raise FileManagerError('Le nom du fichier est invalide.')
    path = _media_path(Path(chapter_relative(lesson)) / config['folder'] / filename)
    if path.suffix.lower() not in config['extensions']:
        raise FileManagerError('Ce type de fichier ne peut pas être supprimé depuis cette catégorie.')
    if not path.is_file():
        raise FileManagerError('Le fichier sélectionné n’existe plus.')
    relative_path = path.relative_to(_media_root()).as_posix()
    if lesson.__class__.objects.filter(pdf=relative_path).exists():
        raise FileManagerError(
            'Ce fichier est lié au champ PDF historique de la leçon; il n’a pas été supprimé.'
        )
    path.unlink()
    logger.warning(
        'Admin user %s deleted lesson resource %s',
        admin_user_id,
        relative_path,
    )
    return relative_path


def lesson_catalogue():
    """Return live lesson choices plus their existing canonical chapter paths."""
    from .models import Lesson

    lessons = list(
        Lesson.objects.select_related('course').order_by(
            'course__niveau', 'course__order', 'course_id', 'order', 'pk'
        )
    )
    owners = {}
    for lesson in sorted(
        lessons,
        key=lambda item: (item.course.order, item.course_id, item.pk),
    ):
        key = (
            lesson.course.niveau,
            lesson.order,
            slugify(lesson.title)[:160] or 'lecon',
        )
        owners.setdefault(key, lesson.pk)

    data = []
    for lesson in lessons:
        relative = chapter_relative(lesson, owners=owners).as_posix()
        data.append({
            'id': lesson.pk,
            'level': lesson.course.niveau,
            'label': f'{lesson.order:02d} · {lesson.title}',
            'course': lesson.course.name,
            'chapter_path': relative,
            'chapter_exists': (_media_root() / relative).is_dir(),
        })
    return data


def category_catalogue():
    return [
        {
            'code': key,
            'label': config['label'],
            'folder': config['folder'],
            'prefix': config.get('prefix', ''),
            'extensions': list(config['extensions']),
        }
        for key, config in CATEGORY_CONFIG.items()
    ]
