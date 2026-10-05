from django.urls import path
from . import views

app_name = 'classrooms'

urlpatterns = [
    path('', views.classroom_list, name='list'),
    path('creer/', views.create_classroom, name='create'),
    path('rejoindre/', views.join_classroom, name='join'),
    path('eleves/', views.my_students, name='students'),
    path('<int:pk>/', views.classroom_detail, name='detail'),
    path('<int:pk>/modifier/', views.edit_classroom, name='edit'),
    path('<int:pk>/supprimer/', views.delete_classroom, name='delete'),
    path('<int:pk>/retirer/<int:user_id>/', views.remove_member, name='remove_member'),
    path('<int:pk>/toggle-active/', views.toggle_classroom_active, name='toggle_active'),
    path('<int:pk>/resultats/', views.classroom_results, name='results'),
    path('<int:pk>/resultats/excel/', views.download_class_excel, name='download_excel'),
    path('<int:pk>/resultats/regenerer/', views.regenerate_excel, name='regenerate_excel'),
    path(
        '<int:pk>/quiz/<int:quiz_id>/resultats/excel/',
        views.download_quiz_excel,
        name='download_quiz_excel',
    ),
]
