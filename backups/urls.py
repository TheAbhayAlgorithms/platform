from django.urls import path
from backups import views

app_name = 'backups'

urlpatterns = [
    path('', views.backup_dashboard, name='dashboard'),
    path('trigger/', views.backup_trigger_manual, name='trigger'),
    path('<int:backup_id>/download/', views.backup_download, name='download'),
    path('<int:backup_id>/verify/', views.backup_verify, name='verify'),
]
