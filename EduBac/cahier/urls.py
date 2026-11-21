from django.urls import path

from . import views

app_name = 'cahier'

urlpatterns = [
    path('', views.index, name='index'),
    path('seance/<int:pk>/supprimer/', views.supprimer, name='supprimer'),
    path('lecon/<int:pk>/etat/', views.etat, name='etat'),
    path('lecon/<int:pk>/enregistrer/', views.enregistrer, name='enregistrer'),
]
