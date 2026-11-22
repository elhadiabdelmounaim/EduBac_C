from django.contrib import admin
from django.urls import path
from .models import Course, Lesson, Resources


class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 1
    fields = ('title', 'order', 'duree_prevue_minutes', 'pdf')


class ResourcesInline(admin.StackedInline):
    """Documents de la leçon : autant de fichiers de cours et d'exercices que nécessaire.
    Remplacer le fichier d'une ressource supprime l'ancien fichier."""
    model = Resources
    extra = 1
    fields = (('categorie', 'ordre'), 'name', 'description', 'file', 'type')
    verbose_name = 'Document de la leçon'
    verbose_name_plural = 'Documents de la leçon (Cours, Exercices, autres)'


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('name', 'niveau', 'order')
    list_filter = ('niveau',)
    search_fields = ('name',)
    inlines = [LessonInline]
    ordering = ('niveau', 'order')

    def get_urls(self):
        from .file_manager_admin import (
            file_manager_view,
            replacement_options_view,
        )

        custom_urls = [
            path(
                'gestionnaire-fichiers/remplacements/',
                self.admin_site.admin_view(
                    lambda request: replacement_options_view(request, self)
                ),
                name='education_course_file_manager_replacements',
            ),
            path(
                'gestionnaire-fichiers/',
                self.admin_site.admin_view(
                    lambda request: file_manager_view(request, self)
                ),
                name='education_course_file_manager',
            ),
        ]
        return custom_urls + super().get_urls()


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('title', 'course', 'order', 'duree_prevue', 'documents')
    fieldsets = (
        (None, {'fields': ('course', 'title', 'order')}),
        ('Suivi du temps d’enseignement', {'fields': ('duree_prevue_minutes',)}),
        ('Contenu', {'fields': ('content', 'summary', 'faq', 'pdf'), 'classes': ('collapse',)}),
    )
    list_filter = ('course__niveau', 'course')
    search_fields = ('title', 'content')
    inlines = [ResourcesInline]
    ordering = ('course', 'order')


    @admin.display(description='Durée prévue')
    def duree_prevue(self, obj):
        from .repartition import duree_prevue_minutes
        minutes = duree_prevue_minutes(obj)
        if not minutes:
            return '—'
        h, m = divmod(minutes, 60)
        texte = (f'{h} h {m:02d}' if m else f'{h} h') if h else f'{m} min'
        return texte if obj.duree_prevue_minutes else f'{texte} (répartition)'

    @admin.display(description='Documents')
    def documents(self, obj):
        return obj.resources.count()


@admin.register(Resources)
class ResourcesAdmin(admin.ModelAdmin):
    list_display = ('name', 'categorie', 'type', 'lesson', 'ordre')
    list_filter = ('categorie', 'type', 'lesson__course__niveau')
    search_fields = ('name', 'description', 'lesson__title')
    list_select_related = ('lesson',)


admin.site.index_template = 'admin/edubac_index.html'
