from accounts.models import User


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
                request.edubac_user = user
                # Pour les pages EduBac, request.user = utilisateur session
                if not request.path.startswith('/admin/'):
                    request.user = user
            except User.DoesNotExist:
                request.session.pop('user_id', None)
                request.session.pop('role', None)
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
