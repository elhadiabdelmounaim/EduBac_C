"""Explicit, bounded quiz inputs. Uploaded documents never enter the public library."""
import codecs
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree

from django.conf import settings
from django.utils.text import slugify

from education.media_library import chapter_relative, documents
from ai.quiz_metrics import timed_phase

ALLOWED_EXTENSIONS = {'.txt', '.md', '.pdf', '.docx'}
MAX_UPLOADS = 5
MAX_RESOURCES = 12
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 25 * 1024 * 1024
MAX_DOCUMENT_CHARS = 20000
MAX_PDF_PAGES = 20


@dataclass
class LessonResource:
    value: str
    label: str
    name: str
    path: Path | None = None
    field: object = None

    @contextmanager
    def open(self):
        if self.path is not None:
            with self.path.open('rb') as handle:
                yield handle
        else:
            with self.field.storage.open(self.field.name, 'rb') as handle:
                yield handle


@timed_phase("catalog")
def resource_catalog(lessons):
    """List selectable files without opening any document or guessing a path."""
    lessons = list(lessons)
    owners = {}
    for lesson in sorted(lessons, key=lambda item: (item.course.order, item.course_id, item.pk)):
        key = (lesson.course.niveau, lesson.order, slugify(lesson.title)[:160] or 'lecon')
        owners.setdefault(key, lesson.pk)
    catalog = {}
    for lesson in lessons:
        relative = chapter_relative(lesson, owners)
        choices = {}
        for kind, prefix in (('Sources_IA', ''), ('Cours', 'cours:'), ('Exercices', 'exercices:')):
            for path in documents(lesson, kind, relative=relative):
                value = prefix + path.name
                choices[value] = LessonResource(value, f'{kind} — {path.name}', path.name, path=path)
        root = Path(settings.MEDIA_ROOT).resolve()
        folder = root / relative / 'Cours'
        if folder.resolve().is_relative_to(root) and folder.is_dir():
            for path in sorted(folder.glob('*.md')):
                if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root):
                    value = 'cours:' + path.name
                    choices[value] = LessonResource(value, f'Cours — {path.name}', path.name, path=path)
        if lesson.pdf:
            name = Path(lesson.pdf.name).name
            choices['lesson-pdf'] = LessonResource(
                'lesson-pdf', f'PDF de la leçon — {name}', name, field=lesson.pdf,
            )
        for resource in lesson.resources.all():
            name = Path(resource.file.name).name
            if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            value = f'resource:{resource.pk}'
            choices[value] = LessonResource(
                value, f'{resource.name} — {name}', name, field=resource.file,
            )
        catalog[str(lesson.pk)] = choices
    return catalog


def _text_document(handle):
    raw = handle.read(MAX_DOCUMENT_CHARS * 4 + 1)
    cut = len(raw) > MAX_DOCUMENT_CHARS * 4
    decoder = codecs.getincrementaldecoder('utf-8-sig')(errors='strict')
    text = decoder.decode(raw[:MAX_DOCUMENT_CHARS * 4], final=not cut).strip()
    if '\x00' in text:
        raise ValueError('Ce fichier ne contient pas du texte UTF-8.')
    return text[:MAX_DOCUMENT_CHARS], cut or len(text) > MAX_DOCUMENT_CHARS


def _pdf_document(handle):
    from pypdf import PdfReader
    if not handle.read(5).startswith(b'%PDF-'):
        raise ValueError('Ce fichier n’est pas un PDF valide.')
    handle.seek(0)
    reader = PdfReader(handle)
    if reader.is_encrypted:
        raise ValueError('Les PDF protégés par un mot de passe ne sont pas acceptés.')
    chunks, length, cut = [], 0, len(reader.pages) > MAX_PDF_PAGES
    for page in reader.pages[:MAX_PDF_PAGES]:
        text = (page.extract_text() or '').strip()
        if text:
            chunks.append(text[:max(0, MAX_DOCUMENT_CHARS - length)])
            length += len(text) + 1
        if length >= MAX_DOCUMENT_CHARS:
            cut = True
            break
    text = '\n'.join(chunks).strip()[:MAX_DOCUMENT_CHARS]
    if not text:
        raise ValueError('Aucun texte lisible : utilisez un PDF avec texte sélectionnable ou un fichier TXT. Les scans et images nécessitent un OCR et ne sont pas pris en charge.')
    return text, cut


def _docx_document(handle):
    with ZipFile(handle) as archive:
        if sum(info.file_size for info in archive.infolist()) > 20 * 1024 * 1024:
            raise ValueError('Le document DOCX décompressé est trop volumineux.')
        info = archive.getinfo('word/document.xml')
        if info.file_size > 5 * 1024 * 1024:
            raise ValueError('Le texte du DOCX est trop volumineux.')
        xml = archive.read(info)
    if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
        raise ValueError('Ce document DOCX contient une structure XML non autorisée.')
    root = ElementTree.fromstring(xml)
    paragraphs = []
    for node in root.iter():
        if node.tag.endswith('}p'):
            text = ''.join(child.text or '' for child in node.iter() if child.tag.endswith('}t'))
            if text.strip():
                paragraphs.append(text.strip())
    text = '\n'.join(paragraphs)
    return text[:MAX_DOCUMENT_CHARS], len(text) > MAX_DOCUMENT_CHARS


def extract_document(handle, name):
    extension = Path(name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError(f'« {name} » : format non accepté. Utilisez TXT, Markdown, PDF texte ou DOCX.')
    handle.seek(0, 2)
    size = handle.tell()
    handle.seek(0)
    if size > MAX_FILE_BYTES:
        raise ValueError(f'« {name} » dépasse la limite de 10 Mo par fichier.')
    if not size:
        raise ValueError(f'« {name} » est vide.')
    try:
        if extension in {'.txt', '.md'}:
            text, cut = _text_document(handle)
        elif extension == '.pdf':
            text, cut = _pdf_document(handle)
        else:
            text, cut = _docx_document(handle)
    except ValueError as exc:
        raise ValueError(f'« {name} » : {exc}') from exc
    except (OSError, UnicodeError, BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise ValueError(f'Impossible de lire « {name} ». Vérifiez le format et, pour le texte, l’encodage UTF-8.') from exc
    except Exception as exc:
        # Parsers may raise format-specific errors. Never silently omit a selected source.
        raise ValueError(f'Impossible d’extraire le texte de « {name} ». Vérifiez le document.') from exc
    if not text.strip():
        raise ValueError(f'« {name} » ne contient aucun texte exploitable.')
    return text.strip(), cut, size


@timed_phase("resources")
def prepare_resources(choices, selected, uploads):
    """Resolve exact selections first; each chosen document must be readable."""
    selected = list(dict.fromkeys(selected))
    uploads = list(uploads)
    if len(uploads) > MAX_UPLOADS:
        raise ValueError('Vous pouvez importer au maximum 5 fichiers par génération.')
    if len(selected) + len(uploads) > MAX_RESOURCES:
        raise ValueError('Choisissez au maximum 12 ressources au total.')
    if any(value not in choices for value in selected):
        raise ValueError('Une ressource sélectionnée est introuvable pour cette leçon. Actualisez la page et vérifiez votre sélection.')
    if any(upload.size > MAX_FILE_BYTES for upload in uploads):
        raise ValueError('Un fichier importé dépasse la limite de 10 Mo.')
    if sum(upload.size for upload in uploads) > MAX_TOTAL_BYTES:
        raise ValueError('Les fichiers importés dépassent la limite totale de 25 Mo.')
    excerpts, warnings, names, size = [], [], [], 0
    for value in selected:
        resource = choices[value]
        try:
            with resource.open() as handle:
                text, cut, document_size = extract_document(handle, resource.name)
        except OSError as exc:
            raise ValueError(f'La ressource « {resource.name} » n’est plus disponible.') from exc
        excerpts.append((resource.name, text))
        size += document_size
        if cut:
            warnings.append(f'« {resource.name} » : seul un extrait est utilisé (20 pages PDF ou 20 000 caractères au maximum).')
    for upload in uploads:
        # Read in memory only, without saving in MEDIA_ROOT or creating a public URL.
        upload.seek(0)
        handle = BytesIO(upload.read(MAX_FILE_BYTES + 1))
        name = Path(upload.name).name
        text, cut, document_size = extract_document(handle, name)
        names.append(name)
        excerpts.append((name, text))
        size += document_size
        if cut:
            warnings.append(f'« {name} » : seul un extrait est utilisé (20 pages PDF ou 20 000 caractères au maximum).')
    if size > MAX_TOTAL_BYTES:
        raise ValueError('Les ressources sélectionnées et importées dépassent la limite totale de 25 Mo.')
    if not excerpts:
        return '', warnings, names
    limit = max(1, int(getattr(settings, 'QUIZ_LESSON_CONTEXT_CHARS', 5000)))
    # Allocate space to every source, rather than silently dropping later documents.
    headers = [f'## Ressource sélectionnée : {name}\n' for name, _ in excerpts]
    remaining = limit - sum(map(len, headers)) - 2 * (len(excerpts) - 1)
    if remaining < 100 * len(excerpts):
        raise ValueError('Le budget de contexte est insuffisant pour ces ressources. Sélectionnez moins de fichiers ou des noms plus courts.')
    parts = []
    for index, ((name, text), header) in enumerate(zip(excerpts, headers)):
        budget = remaining // (len(excerpts) - index)
        excerpt = text[:budget]
        parts.append(header + excerpt)
        remaining -= len(excerpt)
        if len(text) > budget:
            warnings.append(f'« {name} » : texte réduit au budget IA ; choisissez des passages plus ciblés si nécessaire.')
    return '\n\n'.join(parts), warnings, names
