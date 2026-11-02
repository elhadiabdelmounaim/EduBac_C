from django import forms

from .file_manager import (
    CATEGORY_CONFIG,
    FileManagerError,
    MAX_UPLOAD_BYTES,
    category_choices,
    existing_items,
    validate_upload,
)
from .models import Course, Lesson


class FileManagerForm(forms.Form):
    niveau = forms.ChoiceField(label='Niveau scolaire')
    lecon = forms.ModelChoiceField(
        label='Chapitre / leçon',
        queryset=Lesson.objects.none(),
    )
    categorie = forms.ChoiceField(label='Type de ressource')
    titre = forms.CharField(
        label='Titre du contenu',
        max_length=200,
        help_text='Sert de nom de fichier; les caractères spéciaux sont normalisés.',
    )
    description = forms.CharField(
        label='Description (facultative)',
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={'rows': 3}),
    )
    fichier = forms.FileField(
        label='Fichier à importer',
        help_text='Taille maximale : 20 Mo. Les formats acceptés dépendent de la catégorie.',
    )
    remplacer_fichier = forms.ChoiceField(
        label='Fichier existant à remplacer (facultatif)',
        required=False,
        choices=[('', '— Créer un nouveau fichier —')],
        help_text='Choisissez un fichier existant pour conserver exactement son nom.',
    )
    confirmer_remplacement = forms.BooleanField(
        required=False,
        label='Je confirme le remplacement du fichier sélectionné.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        available_levels = set(
            Course.objects.order_by('niveau')
            .values_list('niveau', flat=True)
            .distinct()
        )
        labels = dict(Course.NIVEAU_CHOICES)
        level_choices = [('', '— Choisir un niveau —')]
        level_choices.extend(
            (code, labels.get(code, code))
            for code in sorted(available_levels, key=lambda code: labels.get(code, code).casefold())
        )
        self.fields['niveau'].choices = level_choices
        self.fields['categorie'].choices = [
            ('', '— Choisir un type —'),
            *category_choices(),
        ]

        lessons = Lesson.objects.select_related('course').order_by(
            'course__order', 'course__niveau', 'order', 'title'
        )
        self.fields['lecon'].queryset = lessons

        selected_lesson_id = (
            self.data.get('lecon') if self.is_bound else self.initial.get('lecon')
        )
        selected_category = (
            self.data.get('categorie')
            if self.is_bound
            else self.initial.get('categorie')
        )
        replacement_choices = [('', '— Créer un nouveau fichier —')]
        if selected_lesson_id and selected_category in CATEGORY_CONFIG:
            selected_lesson = (
                Lesson.objects.select_related('course')
                .filter(pk=selected_lesson_id)
                .first()
            )
            if selected_lesson:
                for item in existing_items(selected_lesson, selected_category):
                    key = (
                        f"resource:{item['resource_id']}"
                        if item['resource_id']
                        else f"file:{item['filename']}"
                    )
                    replacement_choices.append((key, item['name']))
        self.fields['remplacer_fichier'].choices = replacement_choices

    def clean(self):
        cleaned_data = super().clean()
        lesson = cleaned_data.get('lecon')
        level = cleaned_data.get('niveau')
        if lesson and level and lesson.course.niveau != level:
            self.add_error('lecon', 'Cette leçon ne correspond pas au niveau sélectionné.')
        return cleaned_data

    def clean_fichier(self):
        upload = self.cleaned_data['fichier']
        category = self.cleaned_data.get('categorie')
        if category in CATEGORY_CONFIG:
            try:
                validate_upload(upload, category)
            except FileManagerError as exc:
                raise forms.ValidationError(str(exc)) from exc
        elif upload.size > MAX_UPLOAD_BYTES:
            raise forms.ValidationError('Le fichier dépasse la limite de 20 Mo.')
        return upload
