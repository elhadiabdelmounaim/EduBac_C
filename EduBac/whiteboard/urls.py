from django.urls import path
from . import share_views, views
from . import correction_views
from . import collab_views
from .tutor_views import board_tutor

app_name = 'whiteboard'

urlpatterns = [
    path('', views.board_list, name='list'),
    path('partager/', share_views.share_create, name='share_create'),
    path('partages/api/', share_views.share_api, name='share_api'),
    path('partages/<int:pk>/', share_views.share_view, name='share_view'),
    path('partages/<int:pk>/image/', share_views.share_image, name='share_image'),
    path('creer/', views.board_create, name='create'),
    path('mes-tableaux/api/', collab_views.my_boards, name='my_boards'),
    path('partager-conversation/', collab_views.share_to_conversation, name='share_to_conversation'),
    path('<int:pk>/sync/', collab_views.sync, name='sync'),
    path('<int:pk>/reglages/', collab_views.update_settings, name='settings'),
    path('<int:pk>/main/', collab_views.give_control, name='control'),
    path('<int:pk>/autoriser/', collab_views.grant, name='grant'),
    path('<int:pk>/main-levee/', collab_views.raise_hand, name='hand'),
    path('<int:pk>/espaces/', collab_views.update_zones, name='zones'),
    path('<int:pk>/partage/', collab_views.share_live, name='share_live'),
    path('<int:pk>/partage/options/', collab_views.share_options, name='share_options'),
    path('<int:pk>/', views.board_room, name='room'),
    path('<int:pk>/api/', views.board_api_content, name='api_content'),
    path('<int:pk>/tutor/', board_tutor, name='tutor'),
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
