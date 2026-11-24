from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    path('', views.history, name='history'),
    path('preferences/', views.preferences, name='preferences'),
    path('tout-lire/', views.mark_all_read, name='mark_all_read'),
    path('<int:pk>/ouvrir/', views.open_notification, name='open'),
    path('api/', views.api_list, name='api_list'),
    path('api/count/', views.api_unread_count, name='api_count'),
    path('api/<int:pk>/read/', views.api_mark_read, name='api_mark_read'),
    path('api/read-all/', views.api_mark_all_read, name='api_mark_all_read'),
    path('telephone/abonner/', views.push_subscribe, name='push_subscribe'),
    path('telephone/desabonner/', views.push_unsubscribe, name='push_unsubscribe'),
    path('telephone/inscription/', views.push_subscribe_inscription, name='push_subscribe_inscription'),
    path('telephone/test/', views.push_test, name='push_test'),
]
