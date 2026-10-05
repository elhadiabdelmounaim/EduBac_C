from django.urls import path
from . import views

app_name = 'ai'

urlpatterns = [
    path('assistant/', views.assistant, name='assistant'),
    path('assistant/lecon/<int:lesson_id>/', views.assistant_lesson, name='assistant_lesson'),
    path('generer-quiz/<int:lesson_id>/', views.generate_quiz, name='generate_quiz'),
]
