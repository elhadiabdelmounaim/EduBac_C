from django.urls import path
from . import views

app_name = 'education'

urlpatterns = [
    path('recherche/', views.search, name='search'),
    path('a-propos/', views.about, name='about'),
    path('whiteboard/', views.whiteboard, name='whiteboard'),
    path('niveaux/', views.niveaux_list, name='niveaux'),
    path('', views.home, name='home'),
    path('niveau/<str:niveau>/', views.niveau_detail, name='niveau_detail'),
    path('cours/<int:pk>/', views.course_detail, name='course_detail'),
    path('lecon/<int:pk>/', views.lesson_detail, name='lesson_detail'),
]
