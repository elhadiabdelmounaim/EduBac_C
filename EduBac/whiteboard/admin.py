from django.contrib import admin
from .models import WhiteboardBoard, WhiteboardShare


@admin.register(WhiteboardBoard)
class WhiteboardBoardAdmin(admin.ModelAdmin):
    list_display = ('title', 'classroom', 'lesson', 'created_by', 'students_can_edit', 'updated_at')
    list_filter = ('students_can_edit', 'is_active')
    search_fields = ('title',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(WhiteboardShare)
class WhiteboardShareAdmin(admin.ModelAdmin):
    list_display = ('title', 'classroom', 'teacher', 'created_at')
    list_filter = ('classroom',)
    search_fields = ('title', 'classroom__name')
    readonly_fields = ('created_at',)
