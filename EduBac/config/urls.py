"""
URL configuration for EduBac.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from accounts.views import admin_teacher_dashboard

urlpatterns = [
    path(
        'admin/ouvrir-espace-professeur/',
        admin_teacher_dashboard,
        name='admin_teacher_dashboard',
    ),
    path('admin/', admin.site.urls),
    path('compte/', include('accounts.urls')),
    path('', include('education.urls')),
    path('quizzes/', include('quizzes.urls')),
    path('classrooms/', include('classrooms.urls')),
    path('ai/', include('ai.urls')),
    path('notifications/', include('notifications.urls')),
    path('chat/', include('chat.urls')),
    path('tableau/', include('whiteboard.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
