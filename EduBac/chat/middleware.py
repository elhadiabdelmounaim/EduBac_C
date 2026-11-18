"""Auth session EduBac pour WebSockets (session['user_id']).

Applique les mêmes règles que SimpleSessionAuthMiddleware : compte actif,
approuvé, e-mail vérifié (ou mot de passe réinitialisé par l'administration),
version de session à jour et pas de changement de mot de passe en attente.
"""
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware


@database_sync_to_async
def get_user(user_id, session_version):
    from accounts.models import User
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        return None
    if (
        not user.is_active
        or user.approval_status == 'pending'
        or (not user.email_verified and not user.password_reset_at)
        or user.must_change_password
        or session_version != user.password_session_version
    ):
        return None
    return user


class EduBacAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        session = scope.get('session')
        user = None
        if session:
            uid = session.get('user_id')
            if uid:
                user = await get_user(uid, session.get('password_session_version', 0))
        scope['user'] = user
        return await super().__call__(scope, receive, send)


def EduBacAuthMiddlewareStack(inner):
    return EduBacAuthMiddleware(inner)
