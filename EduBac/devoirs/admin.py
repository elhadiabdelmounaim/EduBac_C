from django.contrib import admin

from .models import Devoir, FichierDevoir


class FichierInline(admin.TabularInline):
    model = FichierDevoir
    extra = 0
    fields = ('nom', 'fichier', 'verrouille', 'ouverture_le', 'taille')
    readonly_fields = ('taille',)


@admin.register(Devoir)
class DevoirAdmin(admin.ModelAdmin):
    list_display = ('titre', 'teacher', 'date_limite', 'cree_le')
    list_filter = ('classes',)
    search_fields = ('titre', 'consigne')
    filter_horizontal = ('classes',)
    inlines = [FichierInline]
