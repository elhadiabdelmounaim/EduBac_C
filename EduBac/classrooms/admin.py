from django.contrib import admin
from .models import Classroom, ClassroomMember


class ClassroomMemberInline(admin.TabularInline):
    model = ClassroomMember
    extra = 0
    readonly_fields = ('joined_at',)


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'niveau', 'teacher', 'created_at')
    list_filter = ('niveau',)
    search_fields = ('name', 'code')
    readonly_fields = ('code',)
    inlines = [ClassroomMemberInline]


@admin.register(ClassroomMember)
class ClassroomMemberAdmin(admin.ModelAdmin):
    list_display = ('user', 'classroom', 'joined_at')
    list_filter = ('classroom',)
    search_fields = ('user__username',)
