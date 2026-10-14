from django.urls import path
from notifications import views

app_name = 'notifications'

urlpatterns = [
    path('logs/', views.whatsapp_log_list, name='log_list'),
    path('reminders/', views.whatsapp_reminders_dashboard, name='reminders_dashboard'),
    path('reminders/trigger/', views.trigger_reminders_sweep, name='trigger_reminders_sweep'),
    path('send/<int:member_id>/', views.whatsapp_send_manual, name='send_manual'),
    path('retry/<int:log_id>/', views.whatsapp_retry_message, name='retry_message'),
    path('webhook/', views.whatsapp_webhook, name='webhook'),
]

