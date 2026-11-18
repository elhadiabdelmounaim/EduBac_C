"""Permissions Whiteboard — basées sur Classroom existant."""
from django.db.models import Q

from classrooms.models import ClassroomMember


def _user(request):
    return getattr(request, 'edubac_user', None) or request.user


def user_can_access_classroom(user, classroom) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        return True
    if user.is_teacher() and classroom.teacher_id == user.id:
        return True
    if user.is_student():
        return ClassroomMember.objects.filter(classroom=classroom, user=user).exists()
    return False


def user_can_edit_board(user, board) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if user.is_student():
        return False
    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        return True
    if board.created_by_id == user.id:
        return True
    if board.classroom_id:
        if user.is_teacher() and board.classroom.teacher_id == user.id:
            return True
        if user.is_student() and board.students_can_edit:
            return ClassroomMember.objects.filter(
                classroom=board.classroom, user=user
            ).exists()
    elif user.is_teacher() and board.created_by_id == user.id:
        return True
    return False


def is_board_manager(user, board) -> bool:
    """Enseignant propriétaire (ou administrateur) : tous les droits sur le tableau."""
    if not user or not getattr(user, 'is_authenticated', False) or user.is_student():
        return False
    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        return True
    if board.created_by_id == user.id:
        return True
    return bool(user.is_teacher() and board.classroom_id and board.classroom.teacher_id == user.id)


def user_can_access_board(user, board) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        return True
    if board.created_by_id == user.id:
        return True
    if board.classroom_id and board.access_mode == board.ACCESS_CLASS:
        if user_can_access_classroom(user, board.classroom):
            return True
    elif board.classroom_id and user.is_teacher() and board.classroom.teacher_id == user.id:
        return True
    # Partage limité à des élèves choisis (ou tableau sans classe).
    return board.participants.filter(pk=user.pk).exists()


def zone_of(board, user_id):
    """Index de l'espace de travail attribué à l'élève, ou None (tout le tableau)."""
    for index, zone in enumerate(board.zones or []):
        if user_id in (zone.get('members') or []):
            return index
    return None


def board_capabilities(user, board) -> dict:
    """Ce que l'utilisateur peut faire, vérifié côté serveur pour chaque modification."""
    caps = {
        'view': False, 'manage': False, 'control': False,
        'draw': False, 'text': False, 'images': False, 'delete': False,
        'zone': None, 'locked': bool(board.is_locked),
    }
    if not user_can_access_board(user, board):
        return caps
    caps['view'] = True
    if is_board_manager(user, board):
        caps.update(manage=True, draw=True, text=True, images=True, delete=True)
        return caps
    if not user.is_student() or board.is_locked:
        return caps
    if board.controller_id == user.id:
        # Contrôle temporaire : l'élève agit comme l'enseignant sur le contenu.
        caps.update(control=True, draw=True, text=True, images=True, delete=True)
        return caps
    granted = board.editors.filter(pk=user.pk).exists()
    if board.students_can_edit or granted:
        caps.update(
            draw=board.allow_draw or granted,
            text=board.allow_text or granted,
            images=board.allow_images,
            delete=board.allow_delete,
            zone=zone_of(board, user.pk),
        )
    return caps


def accessible_boards(user):
    """Tableaux actifs visibles par l'utilisateur (liste « Whiteboard »)."""
    from .models import WhiteboardBoard
    boards = WhiteboardBoard.objects.filter(is_active=True)
    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        return boards
    if user.is_teacher():
        return boards.filter(Q(created_by=user) | Q(classroom__teacher=user))
    class_ids = ClassroomMember.objects.filter(user=user).values_list('classroom_id', flat=True)
    return boards.filter(
        Q(created_by=user)
        | Q(classroom_id__in=class_ids, access_mode=WhiteboardBoard.ACCESS_CLASS)
        | Q(participants=user)
    ).distinct()


def user_can_view_share(user, share) -> bool:
    """Élève : uniquement sa classe. Professeur : uniquement ses classes."""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        return True
    if share.teacher_id == user.id:
        return True
    if user.is_teacher() and share.classroom.teacher_id == user.id:
        return True
    if user.is_student():
        return ClassroomMember.objects.filter(
            classroom_id=share.classroom_id, user=user,
        ).exists()
    return False


def visible_shares(user):
    from .models import WhiteboardShare
    if not user or not getattr(user, 'is_authenticated', False):
        return WhiteboardShare.objects.none()
    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        return WhiteboardShare.objects.all()
    if user.is_teacher():
        return WhiteboardShare.objects.filter(
            Q(teacher=user) | Q(classroom__teacher=user)
        )
    if user.is_student():
        class_ids = ClassroomMember.objects.filter(user=user).values_list(
            'classroom_id', flat=True,
        )
        return WhiteboardShare.objects.filter(classroom_id__in=class_ids)
    return WhiteboardShare.objects.none()
