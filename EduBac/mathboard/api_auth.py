"""DRF ↔ session EduBac existante (request.edubac_user), avec protection CSRF."""
from rest_framework.authentication import SessionAuthentication


class EduBacSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        user = getattr(request._request, 'edubac_user', None)
        if not user or not user.is_active:
            return None
        self.enforce_csrf(request)
        return (user, None)
