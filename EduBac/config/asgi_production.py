"""Point d'entrée ASGI de production (PythonAnywhere « ASGI », Uvicorn).

    uvicorn --app-dir ~/EduBac/EduBac --uds ${DOMAIN_SOCKET} config.asgi_production:application

- Réglages de production (config.settings_production, .env privé).
- Les sites ASGI de PythonAnywhere n'ont pas de correspondance /static/ :
  Django sert donc lui-même les fichiers statiques (static/ et ceux des
  applications), comme le fait runserver. /media/ n'est jamais servi
  directement : les fichiers privés passent par les vues avec contrôle d'accès.
- Un seul processus Uvicorn : la couche Channels en mémoire suffit. Avec
  plusieurs processus, définir REDIS_URL.
"""
import os

os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings_production'

from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler  # noqa: E402

from .asgi import application as edubac_application  # noqa: E402

application = ASGIStaticFilesHandler(edubac_application)
