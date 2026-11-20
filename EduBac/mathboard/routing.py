from channels.security.websocket import AllowedHostsOriginValidator
from django.urls import re_path

from . import consumers

# Origine vérifiée (ALLOWED_HOSTS) : une page d'un autre site ne peut pas ouvrir
# ce canal avec la session de l'utilisateur.
websocket_urlpatterns = [
    re_path(r'^ws/tableau-maths/(?P<document_id>\d+)/$',
            AllowedHostsOriginValidator(consumers.MathboardConsumer.as_asgi())),
]
