from django.urls import path
from . import live_views, views
from .performance import generation_progress

app_name = 'quizzes'

urlpatterns = [
    # Élève
    path('assignes/', views.assigned_quizzes, name='assigned'),
    path('mes-resultats/', views.my_results, name='my_results'),
    path('mes-erreurs/', views.review_mistakes, name='review_mistakes'),
    path('direct/', live_views.rejoindre, name='live_join'),
    path('<int:pk>/direct/', live_views.lancer, name='live_launch'),
    path('direct/<int:pk>/animer/', live_views.animer, name='live_host'),
    path('direct/<int:pk>/animer/etat/', live_views.etat_hote, name='live_host_state'),
    path('direct/<int:pk>/animer/action/', live_views.action_hote, name='live_host_action'),
    path('direct/<int:pk>/', live_views.jouer, name='live_play'),
    path('direct/<int:pk>/etat/', live_views.etat_eleve, name='live_state'),
    path('direct/<int:pk>/repondre/', live_views.repondre, name='live_answer'),
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
    path('prompt-ia/', views.ai_prompt, name='ai_prompt'),
    path('generation/<uuid:generation_id>/suivi/', generation_progress, name='generation_progress'),
    path('affecter/', views.assign_quiz, name='assign'),
    path('affecter/<int:pk>/', views.assign_quiz, name='assign_quiz'),
    path('resultats-eleves/', views.student_results, name='student_results'),
    path('statistiques/', views.teacher_stats, name='teacher_stats'),
    path('<int:pk>/programmer/', views.schedule_quiz, name='schedule'),
    path('<int:pk>/publier/', views.publish_quiz, name='publish'),
    path('<int:pk>/questions/', views.edit_quiz_questions, name='edit_questions'),
    path('<int:pk>/supprimer/', views.delete_quiz, name='delete'),
    path('tentative/<int:attempt_id>/revision/', views.review_attempt, name='review'),
    path('export-resultats/', views.export_results_csv, name='export_csv'),
    path('export-resultats-excel/', views.export_results_excel, name='export_excel'),
    path('<int:pk>/rejouer/', views.retake_quiz, name='retake'),
    path('<int:pk>/stats-questions/', views.question_stats, name='question_stats'),
    path('<int:pk>/dupliquer/', views.duplicate_quiz, name='duplicate'),
    path('<int:pk>/relancer/', views.remind_pending, name='remind_pending'),
    path('tentative/<int:attempt_id>/commentaire/', views.comment_attempt, name='comment'),
    path('classement/', views.class_ranking, name='ranking'),
]
