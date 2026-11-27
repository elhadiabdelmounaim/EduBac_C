from django.urls import path
from . import info_views, views

app_name = 'education'

urlpatterns = [
    path('recherche/', views.search, name='search'),
    path('recherche/rapide/', views.search_quick, name='search_quick'),
    path('a-propos/', views.about, name='about'),
    path('mentions-legales/', info_views.legal, name='legal'),
    path('confidentialite/', info_views.privacy, name='privacy'),
    path('conditions-utilisation/', info_views.terms, name='terms'),
    path('contact/', info_views.contact, name='contact'),
    path('aide/', info_views.help_page, name='help'),
    path('reperes-bac/', info_views.bac, name='bac'),
    path('whiteboard/', views.whiteboard, name='whiteboard'),
    path('niveaux/', views.niveaux_list, name='niveaux'),
    path('', views.home, name='home'),
    path('bienvenue/', views.welcome, name='welcome'),
    path('niveau/<str:niveau>/', views.niveau_detail, name='niveau_detail'),
    path('cours/<int:pk>/', views.course_detail, name='course_detail'),
    path('lecon/<int:pk>/', views.lesson_detail, name='lesson_detail'),
    path('lecon/<int:pk>/pdf/', views.lesson_pdf, name='lesson_pdf'),
    path('lecon/<int:pk>/cours/', views.lesson_course_html, name='lesson_course_html'),
    path('lecon/<int:pk>/livre-3d/', views.lesson_book_3d, name='lesson_book_3d'),
    path('lecon/<int:pk>/documents/<str:kind>/<str:filename>/', views.lesson_document, name='lesson_document'),
    path('lecon/<int:pk>/ressources/<int:resource_id>/', views.resource_download, name='resource_download'),
]
