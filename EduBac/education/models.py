from django.db import models


class Course(models.Model):
    """
    Cours de mathématiques appartenant à un niveau.
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

    name = models.CharField(max_length=200, verbose_name='Nom du cours')
    niveau = models.CharField(
        max_length=50,
        choices=NIVEAU_CHOICES,
        verbose_name='Niveau',
    )
    description = models.TextField(blank=True, verbose_name='Description')
    order = models.PositiveIntegerField(default=0, verbose_name='Ordre')

    class Meta:
        verbose_name = 'Cours'
        verbose_name_plural = 'Cours'
        ordering = ['niveau', 'order', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_niveau_display()})"

    def get_lessons(self):
        return self.lessons.all().order_by('order')

    def get_quizzes(self):
        from quizzes.models import Quiz
        return Quiz.objects.filter(lesson__course=self)


class Lesson(models.Model):
    """
    Leçon appartenant à un cours de mathématiques.
    Le contenu est la source principale pour l'IA.
    """
    title = models.CharField(max_length=255, verbose_name='Titre')
    content = models.TextField(verbose_name='Contenu pédagogique')
    summary = models.TextField(blank=True, verbose_name='Fiche résumé')
    faq = models.TextField(blank=True, verbose_name='FAQ (une question par ligne: Q?|R)')
    pdf = models.FileField(
        upload_to='lessons/pdfs/',
        blank=True,
        null=True,
        verbose_name='Fichier PDF',
    )
    order = models.PositiveIntegerField(default=0, verbose_name='Ordre')
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='lessons',
        verbose_name='Cours',
    )

    class Meta:
        verbose_name = 'Leçon'
        verbose_name_plural = 'Leçons'
        ordering = ['course', 'order', 'title']

    def __str__(self):
        return f"{self.title} — {self.course.name}"

    def get_content(self):
        from .media_library import course_markdown
        markdown = course_markdown(self)
        return self.content if markdown is None else markdown

    def get_quizzes(self):
        return self.quizzes.all()


    def get_full_pedagogical_text(self) -> str:
        """Texte complet pour l'IA : content DB + resume + fichiers media."""
        from .media_library import ai_source_text
        source_text = ai_source_text(self)
        parts = [source_text] if source_text else []
        if self.content and self.content.strip():
            parts.append(self.content.strip())
        if self.summary and self.summary.strip():
            parts.append("## Resume\n" + self.summary.strip())
        if self.faq and self.faq.strip():
            parts.append("## FAQ\n" + self.faq.strip())

        try:
            from pathlib import Path
            from django.conf import settings
            from .media_library import LEVEL_FOLDERS
            media = Path(settings.MEDIA_ROOT)
            folder = LEVEL_FOLDERS.get(self.course.niveau, '')
            level_dir = media / 'lessons' / folder if folder else None
            if level_dir and level_dir.is_dir():
                order = self.order or 1
                for name in (f'{order:02d}.md', f'{order:02d}_logique.md'):
                    md = level_dir / name
                    if md.is_file() and md.stat().st_size > 50:
                        text = md.read_text(encoding='utf-8', errors='ignore').strip()
                        if text and (not parts or text != parts[0]):
                            parts.append(text)
                        break
                pdf_file = level_dir / f'{order:02d}.pdf'
                if pdf_file.is_file() and pdf_file.stat().st_size > 100:
                    extracted = self._extract_pdf_text(pdf_file)
                    if extracted and len(extracted) > 80:
                        parts.append("## Extrait PDF\n" + extracted[:12000])
            if self.pdf:
                try:
                    path = Path(self.pdf.path)
                    if path.is_file() and path.stat().st_size > 100:
                        extracted = self._extract_pdf_text(path)
                        if extracted and len(extracted) > 80:
                            parts.append("## Extrait PDF lecon\n" + extracted[:12000])
                except Exception:
                    pass
        except Exception:
            pass

        full = "\n\n".join(parts).strip()
        if not full:
            full = (
                f"Lecon : {self.title}\n"
                f"Niveau : {self.course.get_niveau_display()}\n"
                "Contenu detaille non encore renseigne dans la base."
            )
        return full

    @staticmethod
    def _extract_pdf_text(path) -> str:
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            chunks = []
            for page in reader.pages[:15]:
                txt = page.extract_text() or ''
                if txt.strip():
                    chunks.append(txt.strip())
            return "\n".join(chunks)
        except Exception:
            return ''

    def get_ai_help(self, source_file=None):
        """Contexte pedagogique pour le service IA.

        Les TXT de Sources_IA sont relus à chaque appel et passent avant
        le résumé, la FAQ et le cours. Le contexte final est limité à
        QUIZ_LESSON_CONTEXT_CHARS (défaut 5000).
        """
        from django.conf import settings
        limit = int(getattr(settings, "QUIZ_LESSON_CONTEXT_CHARS", 5000))
        summary = (self.summary or "").strip()
        faq = (self.faq or "").strip()
        content = (self.content or "").strip()
        from .media_library import ai_source_text
        source_text = ai_source_text(self, source_file=source_file)
        parts = [source_text] if source_text else []
        if summary and not source_file:
            parts.append("## Resume\n" + summary)
        if faq and not source_file:
            parts.append("## FAQ\n" + faq)
        if content and not source_file:
            parts.append(content)
        contenu = "\n\n".join(parts).strip()
        if not contenu:
            contenu = self.get_full_pedagogical_text()
        suffix = "\n\n[... contenu tronque ...]"
        if len(contenu) > limit:
            contenu = contenu[: max(0, limit - len(suffix))].rstrip() + suffix
        return {
            'niveau': self.course.get_niveau_display(),
            'cours': self.course.name,
            'lecon': self.title,
            'contenu': contenu,
        }


class Resources(models.Model):
    """
    Ressources associées à une leçon (PDF, image, document).
    """
    TYPE_CHOICES = [
        ('pdf', 'PDF'),
        ('image', 'Image'),
        ('doc', 'Document'),
    ]

    name = models.CharField(max_length=200, verbose_name='Nom')
    file = models.FileField(upload_to='resources/', verbose_name='Fichier')
    type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default='pdf',
        verbose_name='Type',
    )
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name='resources',
        verbose_name='Leçon',
    )

    class Meta:
        verbose_name = 'Ressource'
        verbose_name_plural = 'Ressources'

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"

    def get_file_url(self):
        if self.file:
            return self.file.url
        return None

    def delete(self, *args, **kwargs):
        if self.file:
            self.file.delete(save=False)
        super().delete(*args, **kwargs)
