from django.urls import path

from . import api, api_class, views

app_name = 'mathboard'

urlpatterns = [
    path('', views.document_list, name='list'),
    path('<int:pk>/', views.document_editor, name='editor'),
    path('<int:pk>/images/<str:filename>', views.image, name='image'),
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

urlpatterns += [
    path('api/documents/<int:pk>/copie/', api_class.CopyView.as_view(), name='api_copy'),
    path('api/documents/<int:pk>/rendre/', api_class.SubmitView.as_view(), name='api_submit'),
    path('api/documents/<int:pk>/corriger/', api_class.CorrectView.as_view(), name='api_correct'),
    path('api/documents/<int:pk>/copies/', api_class.CopiesView.as_view(), name='api_copies'),
    path('api/documents/<int:pk>/presentation/', api_class.PresentationView.as_view(), name='api_presentation'),
    path('api/documents/<int:pk>/participation/', api_class.ContributionsView.as_view(), name='api_contributions'),
    path('api/documents/<int:pk>/images/', api_class.ImageUploadView.as_view(), name='api_images'),
    path('api/documents/<int:pk>/reconnaissance/', api_class.RecognitionView.as_view(), name='api_recognition'),
    path('convertir/<int:board_id>/', views.convert_legacy, name='convert_legacy'),
]
