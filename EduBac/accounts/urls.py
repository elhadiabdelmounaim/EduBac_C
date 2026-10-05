from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('favoris/', views.my_favorites, name='favorites'),
    path('calendrier/', views.calendar_quizzes, name='calendar'),
    path('badges/', views.my_badges, name='badges'),
    path('connexion/', views.login_view, name='login'),
    path('connexion/eleve/', views.login_student, name='login_student'),
    path('connexion/professeur/', views.login_teacher, name='login_teacher'),
    path('deconnexion/', views.logout_view, name='logout'),
    path('inscription/', views.register, name='register'),
    path('inscription/choix/', views.register_choice, name='register_choice'),
    path('inscription/eleve/', views.register_student, name='register_student'),
    path('inscription/professeur/', views.register_teacher, name='register_teacher'),
    path('profil/', views.profile, name='profile'),
    path('tableau-de-bord/', views.dashboard, name='dashboard'),
    path('progression/', views.my_progress, name='progress'),
    path('mes-cours/', views.my_courses, name='my_courses'),
    path('mes-lecons/', views.my_lessons, name='my_lessons'),
]
