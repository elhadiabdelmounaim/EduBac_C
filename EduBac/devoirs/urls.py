from django.urls import path

from . import views

app_name = 'devoirs'

urlpatterns = [
    path('', views.index, name='index'),
    path('nouveau/', views.creer, name='creer'),
    path('<int:pk>/', views.detail, name='detail'),
    path('<int:pk>/modifier/', views.modifier, name='modifier'),
    path('<int:pk>/supprimer/', views.supprimer, name='supprimer'),
    path('<int:pk>/fichiers/', views.ajouter, name='ajouter'),
    path('fichier/<int:pk>/', views.telecharger, name='telecharger'),
    path('fichier/<int:pk>/verrou/', views.verrou, name='verrou'),
    path('fichier/<int:pk>/supprimer/', views.retirer, name='retirer'),
]
