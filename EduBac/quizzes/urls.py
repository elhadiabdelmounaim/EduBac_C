from django.urls import path
from . import views

app_name = 'quizzes'

urlpatterns = [
    # Élève
    path('assignes/', views.assigned_quizzes, name='assigned'),
    path('mes-resultats/', views.my_results, name='my_results'),
    path('entrainement/', views.training, name='training'),
    path('<int:pk>/', views.quiz_detail, name='detail'),
    path('<int:pk>/commencer/', views.start_quiz, name='start'),
    path('tentative/<int:attempt_id>/', views.take_quiz, name='take'),
    path('tentative/<int:attempt_id>/feedback/<int:question_id>/', views.question_feedback, name='feedback'),
    path('tentative/<int:attempt_id>/resultats/', views.quiz_results, name='results'),
    # Enseignant
    path('gestion/', views.manage_quizzes, name='manage'),
    path('creer/', views.create_quiz, name='create'),
    path('generer-envoyer/', views.teacher_ai_quiz, name='teacher_ai'),
    path('affecter/', views.assign_quiz, name='assign'),
    path('affecter/<int:pk>/', views.assign_quiz, name='assign_quiz'),
    path('resultats-eleves/', views.student_results, name='student_results'),
    path('statistiques/', views.teacher_stats, name='teacher_stats'),
    path('<int:pk>/programmer/', views.schedule_quiz, name='schedule'),
    path('<int:pk>/publier/', views.publish_quiz, name='publish'),
    path('<int:pk>/questions/', views.edit_quiz_questions, name='edit_questions'),
    path('tentative/<int:attempt_id>/revision/', views.review_attempt, name='review'),
    path('export-resultats/', views.export_results_csv, name='export_csv'),
    path('export-resultats-excel/', views.export_results_excel, name='export_excel'),
    path('<int:pk>/rejouer/', views.retake_quiz, name='retake'),
    path('<int:pk>/stats-questions/', views.question_stats, name='question_stats'),
    path('<int:pk>/dupliquer/', views.duplicate_quiz, name='duplicate'),
    path('tentative/<int:attempt_id>/commentaire/', views.comment_attempt, name='comment'),
    path('analyse-erreurs/', views.error_analysis, name='errors'),
    path('classement/', views.class_ranking, name='ranking'),
]
