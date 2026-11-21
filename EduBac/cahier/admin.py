from django.contrib import admin

from .models import Seance, SeanceElement


class SeanceElementInline(admin.TabularInline):
    model = SeanceElement
    extra = 0
    fields = ('order', 'partie', 'sous_titre', 'title', 'key')


@admin.register(Seance)
class SeanceAdmin(admin.ModelAdmin):
    list_display = ('date', 'classroom', 'lesson', 'teacher', 'updated_at')
    list_filter = ('date', 'classroom')
    search_fields = ('lesson__title', 'classroom__name', 'teacher__username')
    list_select_related = ('classroom', 'lesson', 'teacher')
    inlines = [SeanceElementInline]
