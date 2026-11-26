from django.urls import path

from . import views

app_name = 'cahier'

urlpatterns = [
    path('', views.index, name='index'),
    path('niveau/<slug:niveau>/', views.niveau, name='niveau'),
    path('niveau/<slug:niveau>/pdf/', views.niveau_pdf, name='niveau_pdf'),
    path('seance/<int:pk>/pdf/', views.seance_pdf, name='seance_pdf'),
    path('seance/<int:pk>/observations/', views.observations, name='observations'),
    path('seance/<int:pk>/supprimer/', views.supprimer, name='supprimer'),
    path('lecon/<int:pk>/etat/', views.etat, name='etat'),
    path('classe/<int:pk>/acces/', views.acces_lecons, name='acces'),
    path('lecon/<int:pk>/enregistrer/', views.enregistrer, name='enregistrer'),
]
