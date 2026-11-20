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
    source_title = serializers.CharField(source='source.title', read_only=True, default=None)
    presentation = serializers.SerializerMethodField()

    class Meta:
        model = WhiteboardDocument
        fields = ('id', 'title', 'owner', 'owner_name', 'classroom', 'classroom_name', 'lesson',
                  'level', 'chapter', 'students_can_edit', 'class_visible', 'is_archived', 'revision',
                  'accepts_submissions', 'due_at', 'source', 'source_title', 'submission_status',
                  'submitted_at', 'returned_at', 'grade', 'feedback', 'presentation',
                  'created_at', 'updated_at', 'access')
        read_only_fields = ('owner', 'revision', 'created_at', 'updated_at', 'source', 'submission_status',
                            'submitted_at', 'returned_at', 'grade', 'feedback')

    def get_presentation(self, obj):
        return presentation_data(obj)

    def validate(self, attrs):
        instance = self.instance
        if instance is not None and instance.submission_status:
            locked = {'classroom', 'students_can_edit', 'class_visible', 'accepts_submissions', 'due_at'} & set(attrs)
            if locked:
                raise serializers.ValidationError('Une copie d’élève ne se partage pas.')
        return attrs

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


PRESENTATION_TIMEOUT = 90  # secondes


def presentation_data(document):
    """Présentation en cours (« suivez-moi ») ou None."""
    import time
    data = document.presentation or {}
    # Sans signal du présentateur depuis 90 s (onglet fermé, coupure) : terminée.
    if not document.presenter_id or not data or time.time() - data.get('at', 0) > PRESENTATION_TIMEOUT:
        return None
    presenter = document.presenter
    return {**{k: v for k, v in data.items() if k != 'at'}, 'user': document.presenter_id,
            'name': presenter.get_full_name() or presenter.username}


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
