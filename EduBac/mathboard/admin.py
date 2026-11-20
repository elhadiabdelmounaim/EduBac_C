from django.contrib import admin

from .models import (
    WhiteboardDocument, WhiteboardMember, WhiteboardOperation, WhiteboardPage, WhiteboardSession,
    WhiteboardSnapshot,
)


class PageInline(admin.TabularInline):
    model = WhiteboardPage
    fields = ('position', 'uid', 'title', 'background')
    extra = 0


class MemberInline(admin.TabularInline):
    model = WhiteboardMember
    fields = ('user', 'role', 'added_by')
    raw_id_fields = ('user', 'added_by')
    extra = 0


@admin.register(WhiteboardDocument)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'owner', 'classroom', 'revision', 'is_archived', 'updated_at')
    list_filter = ('is_archived',)
    search_fields = ('title', 'owner__username')
    raw_id_fields = ('owner', 'classroom', 'lesson')
    inlines = (PageInline, MemberInline)


@admin.register(WhiteboardOperation)
class OperationAdmin(admin.ModelAdmin):
    list_display = ('document', 'revision', 'kind', 'author', 'created_at')
    list_filter = ('kind',)
    readonly_fields = [f.name for f in WhiteboardOperation._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(WhiteboardSnapshot)
class SnapshotAdmin(admin.ModelAdmin):
    list_display = ('document', 'revision', 'kind', 'label', 'created_at')
    list_filter = ('kind',)
    exclude = ('data',)


@admin.register(WhiteboardSession)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('document', 'user', 'page_uid', 'last_seen')
