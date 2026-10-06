import json
import logging
import time

from django.core.cache import cache
from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from ai.providers import AIProviderError
from .models import WhiteboardBoard
from .permissions import user_can_access_board, user_can_edit_board
from .tutor_service import build_context, tutor_response
from .tutor_validation import TutorInputError, validate_request

logger = logging.getLogger(__name__)


def rate_limit(user_id):
    minute = int(time.time() // 60)
    for key, limit in ((f'wb-tutor:user:{user_id}:{minute}', 12),
                       (f'wb-tutor:global:{minute}', 60)):
        if cache.add(key, 1, timeout=65):
            count = 1
        else:
            try:
                count = cache.incr(key)
            except ValueError:
                cache.add(key, 1, timeout=65)
                count = 1
        if count > limit:
            raise AIProviderError('Trop de demandes. Réessaie dans une minute.', code='rate_limit')


@require_POST
def board_tutor(request, pk):
    user = getattr(request, 'edubac_user', None)
    if user is None:
        return JsonResponse({'error': 'Connecte-toi pour utiliser le tuteur.'}, status=401)
    board = get_object_or_404(
        WhiteboardBoard.objects.select_related('lesson__course', 'classroom'), pk=pk, is_active=True)
    if not user_can_access_board(user, board):
        return JsonResponse({'error': 'Accès refusé à ce tableau.'}, status=403)
    try:
        if len(request.body) > 2_400_000:
            raise TutorInputError('Le tableau envoyé est trop volumineux.')
        payload = validate_request(json.loads(request.body))
    except (ValueError, UnicodeDecodeError, RequestDataTooBig) as exc:
        message = str(exc) if isinstance(exc, TutorInputError) else 'Requête JSON invalide ou trop volumineuse.'
        return JsonResponse({'error': message}, status=400)
    history_key = f'whiteboard_tutor_{board.pk}'
    history = request.session.get(history_key, [])
    context = build_context(board, user, payload, history)
    try:
        rate_limit(user.pk)
        result = tutor_response(context, payload['image'])
    except AIProviderError as exc:
        # Log only a safe error code, never upstream content containing keys/images.
        logger.warning('Whiteboard tutor failed: %s', exc.code)
        error = {
            'rate_limit': 'Trop de demandes. Réessaie dans une minute.',
            'invalid_response': 'La réponse IA n’a pas passé les contrôles. Réessaie.',
            'vision_unsupported': 'Ce fournisseur ne peut pas lire les images. Transcris l’exercice dans le tableau.',
            'missing_api_key': 'Le tuteur IA n’est pas configuré. Contacte ton professeur.',
        }.get(exc.code, 'Le tuteur est momentanément indisponible. Ta question est conservée ; réessaie.')
        return JsonResponse({'error': error}, status=429 if exc.code == 'rate_limit' else 502)
    request.session[history_key] = (history + [
        {'role': 'user', 'content': payload['question']},
        {'role': 'assistant', 'content': result['reply'][:4000]},
    ])[-12:]
    # Bound per-session tutor history across boards as well as within a board.
    keys = [key for key in request.session.keys() if key.startswith('whiteboard_tutor_')]
    for key in keys[:-5]:
        if key != history_key:
            del request.session[key]
    result['context'] = {key: context[key] for key in ('niveau', 'lesson', 'exercise')}
    result['can_edit'] = user_can_edit_board(user, board)
    return JsonResponse(result)
