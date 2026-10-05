from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    path('api/', views.api_list, name='api_list'),
    path('api/count/', views.api_unread_count, name='api_count'),
    path('api/<int:pk>/read/', views.api_mark_read, name='api_mark_read'),
    path('api/read-all/', views.api_mark_all_read, name='api_mark_all_read'),
]
