from django.contrib import admin

from .models import Devoir, FichierDevoir, FichierRendu, RenduDevoir


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


class FichierRenduInline(admin.TabularInline):
    model = FichierRendu
    extra = 0
    fields = ('nom', 'fichier', 'taille')
    readonly_fields = ('taille',)


@admin.register(RenduDevoir)
class RenduDevoirAdmin(admin.ModelAdmin):
    list_display = ('devoir', 'eleve', 'rendu_le', 'note', 'corrige_le')
    list_filter = ('devoir',)
    search_fields = ('eleve__username', 'eleve__last_name', 'devoir__titre')
    inlines = [FichierRenduInline]
