from django.contrib import admin
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
