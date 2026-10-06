import json
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST, require_GET, require_http_methods
from accounts.decorators import login_required_simple, teacher_required
from classrooms.models import Classroom, ClassroomMember
from .models import WhiteboardBoard
from .permissions import user_can_access_board, user_can_edit_board
from django.db.models import Q
from education.models import Lesson


def _user(request):
    return getattr(request, 'edubac_user', None) or request.user


@login_required_simple
def board_list(request):
    """Liste des tableaux accessibles (enseignant ou élève)."""
    user = _user(request)
    if getattr(user, 'role', '') == 'teacher':
        boards = WhiteboardBoard.objects.filter(
            created_by=user, is_active=True
        ).select_related('classroom', 'lesson')
        classrooms = Classroom.objects.filter(teacher=user, is_active=True)
    else:
        class_ids = ClassroomMember.objects.filter(user=user).values_list(
            'classroom_id', flat=True
        )
        boards = WhiteboardBoard.objects.filter(
            Q(classroom_id__in=class_ids) | Q(created_by=user), is_active=True
        ).select_related('classroom', 'lesson')
        classrooms = Classroom.objects.filter(id__in=class_ids)
    return render(request, 'whiteboard/list.html', {
        'boards': boards,
        'classrooms': classrooms,
        'page_title': 'Whiteboard',
        'is_teacher': getattr(user, 'role', '') == 'teacher',
        'lessons': Lesson.objects.select_related('course').order_by('course__order', 'order'),
    })


@login_required_simple
@require_POST
def board_create(request):
    user = _user(request)
    title = (request.POST.get('title') or 'Nouveau tableau').strip()[:200]
    classroom_id = request.POST.get('classroom') or ''
    lesson_id = request.POST.get('lesson') or ''
    classroom = None
    lesson = None
    if classroom_id:
        if user.role != 'teacher':
            return HttpResponseForbidden('Les élèves créent uniquement des tableaux personnels.')
        classroom = get_object_or_404(Classroom, pk=classroom_id, teacher=user)
    if lesson_id:
        from education.models import Lesson
        lesson = get_object_or_404(Lesson, pk=lesson_id)
    board = WhiteboardBoard.objects.create(
        title=title or 'Nouveau tableau',
        classroom=classroom,
        lesson=lesson,
        created_by=user,
        content={'objects': [], 'version': 1},
        students_can_edit=request.POST.get('students_can_edit') == 'on',
    )
    return redirect('whiteboard:room', pk=board.pk)


@login_required_simple
def board_room(request, pk):
    """Page interactive du tableau."""
    board = get_object_or_404(
        WhiteboardBoard.objects.select_related('classroom', 'lesson', 'created_by'),
        pk=pk,
        is_active=True,
    )
    user = _user(request)
    if not user_can_access_board(user, board):
        return HttpResponseForbidden(
            'Accès refusé : vous n\'êtes pas membre de cette classe.'
        )
    can_edit = user_can_edit_board(user, board)
    return render(request, 'whiteboard/room.html', {
        'board': board,
        'can_edit': can_edit,
        'is_teacher_owner': (
            getattr(user, 'role', '') == 'teacher'
            and (board.created_by_id == user.id
                 or (board.classroom_id and board.classroom.teacher_id == user.id))
        ),
        'page_title': board.title,
        'ws_path': f'/ws/whiteboard/{board.pk}/',
    })


@login_required_simple
@require_http_methods(['GET', 'POST'])
def board_api_content(request, pk):
    """GET/POST contenu JSON du tableau."""
    board = get_object_or_404(WhiteboardBoard, pk=pk, is_active=True)
    user = _user(request)
    if not user_can_access_board(user, board):
        return JsonResponse({'error': 'Accès refusé'}, status=403)

    if request.method == 'GET':
        return JsonResponse({
            'id': board.pk,
            'title': board.title,
            'content': board.content or {'objects': [], 'version': 1},
            'students_can_edit': board.students_can_edit,
            'can_edit': user_can_edit_board(user, board),
            'updated_at': board.updated_at.isoformat(),
        })

    if not user_can_edit_board(user, board):
        return JsonResponse({'error': 'Lecture seule'}, status=403)
    try:
        body = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)
    if 'content' in body:
        board.content = body['content']
    if 'title' in body and body['title']:
        board.title = str(body['title'])[:200]
    if 'students_can_edit' in body and getattr(user, 'role', '') == 'teacher':
        board.students_can_edit = bool(body['students_can_edit'])
    board.save()
    return JsonResponse({'ok': True, 'updated_at': board.updated_at.isoformat()})


@login_required_simple
@require_POST
def board_delete(request, pk):
    board = get_object_or_404(WhiteboardBoard, pk=pk, created_by=_user(request))
    board.is_active = False
    board.save(update_fields=['is_active'])
    return redirect('whiteboard:list')


@login_required_simple
@require_POST
def board_duplicate(request, pk):
    board = get_object_or_404(WhiteboardBoard, pk=pk, created_by=_user(request))
    clone = WhiteboardBoard.objects.create(
        title=f'{board.title} (copie)',
        classroom=board.classroom,
        lesson=board.lesson,
        created_by=_user(request),
        content=board.content,
        students_can_edit=board.students_can_edit,
    )
    return redirect('whiteboard:room', pk=clone.pk)


@teacher_required
@require_POST
def board_rename(request, pk):
    board = get_object_or_404(WhiteboardBoard, pk=pk, created_by=_user(request))
    title = (request.POST.get('title') or '').strip()[:200]
    if title:
        board.title = title
        board.save(update_fields=['title', 'updated_at'])
    return redirect('whiteboard:room', pk=board.pk)
