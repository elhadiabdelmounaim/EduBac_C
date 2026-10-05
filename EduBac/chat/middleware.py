"""Auth session EduBac pour WebSockets (session['user_id'])."""
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware


@database_sync_to_async
def get_user(user_id):
    from accounts.models import User
    try:
        return User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return None


class EduBacAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        session = scope.get('session')
        user = None
        if session:
            uid = session.get('user_id')
            if uid:
                user = await get_user(uid)
        scope['user'] = user
        return await super().__call__(scope, receive, send)


def EduBacAuthMiddlewareStack(inner):
    return EduBacAuthMiddleware(inner)
