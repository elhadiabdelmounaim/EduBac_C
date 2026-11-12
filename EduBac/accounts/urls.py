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
    path('verification-email/', views.email_verification_pending, name='email_verification_pending'),
    path('verification-email/renvoyer/', views.resend_verification, name='resend_verification'),
    path('verification-email/confirmer/<str:token>/', views.confirm_email, name='confirm_email'),
    path('mot-de-passe/changer/', views.change_password, name='change_password'),
    path('inscription/', views.register, name='register'),
    path('inscription/choix/', views.register_choice, name='register_choice'),
    path('inscription/eleve/', views.register_student, name='register_student'),
    path('inscription/professeur/', views.register_teacher, name='register_teacher'),
    path('administration/', views.admin_dashboard, name='admin_dashboard'),
    path(
        'administration/eleves/<int:user_id>/mot-de-passe/',
        views.confirm_student_password_reset,
        name='confirm_student_password_reset',
    ),
    path(
        'administration/eleves/<int:user_id>/mot-de-passe/reinitialiser/',
        views.reset_student_password,
        name='reset_student_password',
    ),
    path(
        'administration/inscriptions/<int:user_id>/',
        views.review_registration,
        name='review_registration',
    ),
    path('profil/', views.profile, name='profile'),
    path('tableau-de-bord/', views.dashboard, name='dashboard'),
    path(
        'espace-professeur/',
        views.teacher_dashboard,
        name='teacher_portal',
    ),
    path('progression/', views.my_progress, name='progress'),
    path('mes-cours/', views.my_courses, name='my_courses'),
    path('mes-lecons/', views.my_lessons, name='my_lessons'),
]
