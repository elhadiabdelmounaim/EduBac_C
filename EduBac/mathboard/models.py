"""Tableau mathématique collaboratif (nouvelle génération).

Source de vérité : la base de données. Chaque modification est une opération
numérotée (révision du document) enregistrée dans WhiteboardOperation ; l'état
courant de chaque page est conservé dans WhiteboardPage.objects pour un
chargement rapide, et des instantanés (WhiteboardSnapshot) permettent de
restaurer une version. Redis / WebSocket ne servent qu'à diffuser.

Utilisateurs, rôles et classes : modèles existants (accounts, classrooms).
"""
import uuid

from django.conf import settings
from django.db import models


class WhiteboardDocument(models.Model):
    title = models.CharField('Titre', max_length=200)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='math_documents', verbose_name='Propriétaire')
    classroom = models.ForeignKey(
        'classrooms.Classroom', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='math_documents', verbose_name='Classe partagée')
    lesson = models.ForeignKey(
        'education.Lesson', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='math_documents', verbose_name='Leçon')
    # Contexte pédagogique transmis à l'assistant IA.
    level = models.CharField('Niveau', max_length=50, blank=True)
    chapter = models.CharField('Chapitre', max_length=200, blank=True)
    students_can_edit = models.BooleanField('Les élèves de la classe peuvent modifier', default=False)
    # Faux : document préparé pour la classe, que les élèves ne voient pas encore.
    class_visible = models.BooleanField('Visible par les élèves de la classe', default=True)
    revision = models.PositiveBigIntegerField(default=0, editable=False)
    is_archived = models.BooleanField('Archivé', default=False)

    # --- Travail à rendre -------------------------------------------------
    # Document du professeur : les élèves de la classe peuvent en faire leur copie.
    accepts_submissions = models.BooleanField('Travail à rendre', default=False)
    due_at = models.DateTimeField('À rendre avant', null=True, blank=True)
    # Copie d'un élève : `source` est le sujet du professeur.
    STATUS_DRAFT, STATUS_SUBMITTED, STATUS_RETURNED = 'draft', 'submitted', 'returned'
    STATUSES = [(STATUS_DRAFT, 'En cours'), (STATUS_SUBMITTED, 'Rendu'), (STATUS_RETURNED, 'Corrigé')]
    source = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='copies', verbose_name='Sujet')
    submission_status = models.CharField('État du travail', max_length=10, choices=STATUSES, blank=True)
    submitted_at = models.DateTimeField('Rendu le', null=True, blank=True)
    returned_at = models.DateTimeField('Corrigé le', null=True, blank=True)
    grade = models.CharField('Note', max_length=20, blank=True)
    feedback = models.TextField('Appréciation', blank=True)

    # --- Mode présentation (« suivez-moi ») --------------------------------
    presenter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='Présentateur')
    # {"page": uid, "cx": x, "cy": y, "w": largeur visible, "h": hauteur visible} (coordonnées de scène)
    presentation = models.JSONField(default=dict, blank=True)

    # Tableau de l'ancien module converti en ce document.
    legacy_board = models.ForeignKey(
        'whiteboard.WhiteboardBoard', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='math_documents', verbose_name='Ancien tableau converti')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-updated_at',)
        verbose_name = 'Document de tableau'
        verbose_name_plural = 'Documents de tableau'
        constraints = [
            models.UniqueConstraint(fields=('source', 'owner'), name='mathboard_one_copy_per_student'),
        ]

    @property
    def is_copy(self):
        return bool(self.source_id and self.submission_status)

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # La révision n'est modifiée que par le moteur d'opérations (update_fields
        # explicite) : un enregistrement depuis une copie ancienne (réglages,
        # administration) ne doit jamais la faire reculer.
        if self.pk and kwargs.get('update_fields') is None and not kwargs.get('force_insert'):
            kwargs['update_fields'] = [
                f.name for f in self._meta.concrete_fields if not f.primary_key and f.name != 'revision']
        super().save(*args, **kwargs)


class WhiteboardPage(models.Model):
    BACKGROUNDS = [
        ('blank', 'Uni'), ('grid', 'Quadrillage'), ('dots', 'Pointillés'),
        ('lines', 'Lignes'), ('axes', 'Repère'),
    ]
    document = models.ForeignKey(WhiteboardDocument, on_delete=models.CASCADE, related_name='pages')
    uid = models.CharField(max_length=64)  # identifiant stable choisi par le client
    position = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=200, blank=True)
    background = models.CharField(max_length=10, choices=BACKGROUNDS, default='blank')
    # {identifiant d'objet: objet} — état courant matérialisé de la page.
    content = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('position', 'id')
        constraints = [
            models.UniqueConstraint(fields=('document', 'uid'), name='mathboard_page_uid_unique'),
        ]
        verbose_name = 'Page'
        verbose_name_plural = 'Pages'

    def __str__(self):
        return f'{self.document} — page {self.position + 1}'


class WhiteboardMember(models.Model):
    ROLE_VIEWER, ROLE_EDITOR, ROLE_MANAGER = 'viewer', 'editor', 'manager'
    ROLES = [(ROLE_VIEWER, 'Lecture'), (ROLE_EDITOR, 'Modification'), (ROLE_MANAGER, 'Gestion')]
    document = models.ForeignKey(WhiteboardDocument, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='math_memberships')
    role = models.CharField(max_length=10, choices=ROLES, default=ROLE_VIEWER)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('document', 'user'), name='mathboard_member_unique'),
        ]
        verbose_name = 'Membre'
        verbose_name_plural = 'Membres'


class WhiteboardOperation(models.Model):
    """Journal append-only des opérations acceptées."""
    document = models.ForeignKey(WhiteboardDocument, on_delete=models.CASCADE, related_name='operations')
    revision = models.PositiveBigIntegerField()
    op_id = models.CharField(max_length=64)  # fourni par le client : idempotence
    kind = models.CharField(max_length=32)
    page_uid = models.CharField(max_length=64, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    payload = models.JSONField(default=dict)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    client_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('revision',)
        constraints = [
            models.UniqueConstraint(fields=('document', 'revision'), name='mathboard_op_revision_unique'),
            models.UniqueConstraint(fields=('document', 'op_id'), name='mathboard_op_id_unique'),
        ]
        verbose_name = 'Opération'
        verbose_name_plural = 'Opérations'


class WhiteboardSnapshot(models.Model):
    KIND_AUTO, KIND_MANUAL, KIND_BEFORE_RESTORE = 'auto', 'manual', 'before_restore'
    KINDS = [(KIND_AUTO, 'Automatique'), (KIND_MANUAL, 'Manuel'), (KIND_BEFORE_RESTORE, 'Avant restauration')]
    document = models.ForeignKey(WhiteboardDocument, on_delete=models.CASCADE, related_name='snapshots')
    revision = models.PositiveBigIntegerField()
    kind = models.CharField(max_length=16, choices=KINDS, default=KIND_AUTO)
    label = models.CharField(max_length=200, blank=True)
    data = models.JSONField()  # {"pages": [...]} : état complet
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-revision', '-id')
        verbose_name = 'Version'
        verbose_name_plural = 'Versions'


class WhiteboardSession(models.Model):
    """Connexion active d'un utilisateur (présence, curseur, page affichée)."""
    document = models.ForeignKey(WhiteboardDocument, on_delete=models.CASCADE, related_name='sessions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    client_id = models.CharField(max_length=64, default=uuid.uuid4)
    page_uid = models.CharField(max_length=64, blank=True)
    cursor = models.JSONField(default=dict, blank=True)
    connected_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('document', 'client_id'), name='mathboard_session_unique'),
        ]
        verbose_name = 'Session'
        verbose_name_plural = 'Sessions'
