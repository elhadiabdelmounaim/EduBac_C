from django.urls import path

from . import api, views

app_name = 'mathboard'

urlpatterns = [
    path('', views.document_list, name='list'),
    path('<int:pk>/', views.document_editor, name='editor'),
    path('api/documents/', api.DocumentListView.as_view(), name='api_documents'),
    path('api/documents/<int:pk>/', api.DocumentDetailView.as_view(), name='api_document'),
    path('api/documents/<int:pk>/etat/', api.DocumentStateView.as_view(), name='api_state'),
    path('api/documents/<int:pk>/operations/', api.OperationsView.as_view(), name='api_operations'),
    path('api/documents/<int:pk>/membres/', api.MemberListView.as_view(), name='api_members'),
    path('api/documents/<int:pk>/membres/<int:member_id>/', api.MemberDetailView.as_view(), name='api_member'),
    path('api/documents/<int:pk>/versions/', api.SnapshotListView.as_view(), name='api_snapshots'),
    path('api/documents/<int:pk>/versions/<int:snapshot_id>/', api.SnapshotDetailView.as_view(), name='api_snapshot'),
    path('api/documents/<int:pk>/versions/<int:snapshot_id>/restaurer/', api.SnapshotRestoreView.as_view(),
         name='api_snapshot_restore'),
]

urlpatterns += [
    path('api/calcul/', api.CalculView.as_view(), name='api_calcul'),
    path('api/documents/<int:pk>/presence/', api.PresenceView.as_view(), name='api_presence'),
    path('api/documents/<int:pk>/export/', api.ExportView.as_view(), name='api_export'),
    path('api/documents/importer/', api.ImportView.as_view(), name='api_import'),
    path('api/documents/<int:pk>/ia/<str:action>/', api.AssistantView.as_view(), name='api_ai'),
]
