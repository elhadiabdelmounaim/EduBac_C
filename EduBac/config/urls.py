"""
URL configuration for EduBac.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from accounts.views import admin_teacher_dashboard
from config import client_errors, pwa, seo

urlpatterns = [
    path(
        'admin/ouvrir-espace-professeur/',
        admin_teacher_dashboard,
        name='admin_teacher_dashboard',
    ),
    path('admin/', admin.site.urls),
    # Application installable (PWA) : à la racine pour couvrir tout le site.
    path('manifest.webmanifest', pwa.manifest, name='pwa_manifest'),
    path('service-worker.js', pwa.service_worker, name='pwa_service_worker'),
    path('hors-ligne/', pwa.offline, name='pwa_offline'),
    path('erreurs-client/', client_errors.client_error, name='client_error'),
    path('robots.txt', seo.robots_txt, name='robots_txt'),
    path('sitemap.xml', seo.sitemap_xml, name='sitemap'),
    path('compte/', include('accounts.urls')),
    path('', include('education.urls')),
    path('quizzes/', include('quizzes.urls')),
    path('classrooms/', include('classrooms.urls')),
    path('ai/', include('ai.urls')),
    path('notifications/', include('notifications.urls')),
    path('chat/', include('chat.urls')),
    path('tableau/', include('whiteboard.urls')),
    path('tableau-maths/', include('mathboard.urls')),
    path('cahier-de-textes/', include('cahier.urls')),
    path('devoirs/', include('devoirs.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
