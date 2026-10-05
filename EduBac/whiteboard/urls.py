from django.urls import path
from . import views
from . import correction_views

app_name = 'whiteboard'

urlpatterns = [
    path('', views.board_list, name='list'),
    path('creer/', views.board_create, name='create'),
    path('<int:pk>/', views.board_room, name='room'),
    path('<int:pk>/api/', views.board_api_content, name='api_content'),
    path('<int:pk>/supprimer/', views.board_delete, name='delete'),
    path('<int:pk>/dupliquer/', views.board_duplicate, name='duplicate'),
    path('<int:pk>/renommer/', views.board_rename, name='rename'),
    # Correction quiz (objets structurés)
    path(
        'correction/<int:attempt_id>/<int:question_id>/',
        correction_views.correction_page,
        name='quiz_correction',
    ),
    path(
        'correction/<int:attempt_id>/<int:question_id>/api/',
        correction_views.correction_api,
        name='quiz_correction_api',
    ),
]
