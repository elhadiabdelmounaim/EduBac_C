from rest_framework import serializers

from classrooms.models import Classroom
from education.models import Lesson

from .models import WhiteboardDocument, WhiteboardMember, WhiteboardSnapshot


class DocumentSerializer(serializers.ModelSerializer):
    owner_name = serializers.SerializerMethodField()
    classroom_name = serializers.CharField(source='classroom.name', read_only=True, default=None)
    classroom = serializers.PrimaryKeyRelatedField(queryset=Classroom.objects.all(), required=False, allow_null=True)
    lesson = serializers.PrimaryKeyRelatedField(queryset=Lesson.objects.all(), required=False, allow_null=True)
    access = serializers.SerializerMethodField()

    class Meta:
        model = WhiteboardDocument
        fields = ('id', 'title', 'owner', 'owner_name', 'classroom', 'classroom_name', 'lesson',
                  'level', 'chapter', 'students_can_edit', 'is_archived', 'revision',
                  'created_at', 'updated_at', 'access')
        read_only_fields = ('owner', 'revision', 'created_at', 'updated_at')

    def get_owner_name(self, obj):
        return obj.owner.get_full_name() or obj.owner.username

    def get_access(self, obj):
        levels = self.context.get('levels') or {}
        return levels.get(obj.pk)

    def validate_title(self, value):
        value = ' '.join(value.split())
        if not value:
            raise serializers.ValidationError('Le titre est obligatoire.')
        return value


class MemberSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = WhiteboardMember
        fields = ('id', 'user', 'username', 'name', 'role', 'created_at')
        read_only_fields = ('created_at',)

    def get_name(self, obj):
        return obj.user.get_full_name() or obj.user.username


class SnapshotSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = WhiteboardSnapshot
        fields = ('id', 'revision', 'kind', 'label', 'created_by', 'created_by_name', 'created_at')

    def get_created_by_name(self, obj):
        user = obj.created_by
        return (user.get_full_name() or user.username) if user else None
