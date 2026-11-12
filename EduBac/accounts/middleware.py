from accounts.models import User
from django.shortcuts import redirect
from django.urls import reverse
from django.conf import settings


class SimpleSessionAuthMiddleware:
    """
    Auth simple par session['user_id'] — sans django.contrib.auth.login.
    Laisse request.user intact pour /admin/ (auth Django admin).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.edubac_user = None
        uid = request.session.get('user_id')

        if uid:
            try:
                user = User.objects.get(pk=uid)
                session_version = request.session.get(
                    'password_session_version',
                    0,
                )
                if session_version != user.password_session_version:
                    request.session.flush()
                    if not request.path.startswith('/admin/'):
                        request.user = AnonymousEduBacUser()
                    return self.get_response(request)

                if (
                    (not user.email_verified and not user.password_reset_at)
                    or user.approval_status == 'pending'
                    or not user.is_active
                ):
                    request.session.pop('user_id', None)
                    request.session.pop('role', None)
                    request.session.pop('password_session_version', None)
                    if not request.path.startswith('/admin/'):
                        request.user = AnonymousEduBacUser()
                else:
                    request.edubac_user = user
                    # Pour les pages EduBac, request.user = utilisateur session
                    if not request.path.startswith('/admin/'):
                        request.user = user
                    if user.must_change_password:
                        allowed_paths = {
                            reverse('accounts:change_password'),
                            reverse('accounts:logout'),
                        }
                        public_prefixes = (
                            settings.STATIC_URL,
                            settings.MEDIA_URL,
                        )
                        if (
                            request.path not in allowed_paths
                            and not any(
                                prefix and request.path.startswith(prefix)
                                for prefix in public_prefixes
                            )
                        ):
                            return redirect('accounts:change_password')
            except User.DoesNotExist:
                request.session.pop('user_id', None)
                request.session.pop('role', None)
                request.session.pop('password_session_version', None)
                if not request.path.startswith('/admin/'):
                    request.user = AnonymousEduBacUser()
        else:
            if not request.path.startswith('/admin/'):
                request.user = AnonymousEduBacUser()

        return self.get_response(request)


class AnonymousEduBacUser:
    is_authenticated = False
    is_anonymous = True
    is_staff = False
    is_superuser = False
    id = None
    pk = None
    username = ''
    role = ''

    def is_student(self):
        return False

    def is_teacher(self):
        return False

    def get_full_name(self):
        return ''

    def get_role_display(self):
        return ''

    def __str__(self):
        return 'Anonymous'
