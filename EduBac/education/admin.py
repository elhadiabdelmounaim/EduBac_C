from django.contrib import admin
from django.urls import path
from .models import Course, Lesson, Resources


class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 1
    fields = ('title', 'order', 'pdf')


class ResourcesInline(admin.TabularInline):
    model = Resources
    extra = 0


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
    list_display = ('title', 'course', 'order')
    list_filter = ('course__niveau', 'course')
    search_fields = ('title', 'content')
    inlines = [ResourcesInline]
    ordering = ('course', 'order')


@admin.register(Resources)
class ResourcesAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'lesson')
    list_filter = ('type',)


admin.site.index_template = 'admin/edubac_index.html'
