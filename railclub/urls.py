"""
URL configuration for RailClub Connect project.
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from core.views import home, health_check, system_health_dashboard, custom_page_not_found_view, custom_server_error_view

handler404 = 'core.views.custom_page_not_found_view'
handler500 = 'core.views.custom_server_error_view'

urlpatterns = [
    path('', home, name='home'),
    path('health/', health_check, name='health_check'),
    path('system-health/', system_health_dashboard, name='system_health'),
    path('payments/', include('payments.urls')),
    path('renewals/', include('renewals.urls')),
    path('plans/', include('plans.urls')),
    path('members/', include('members.urls')),
    path('portal/', include('portal.urls')),
    path('whatsapp/', include('notifications.urls')),
    path('reports/', include('reports.urls')),
    path('events/', include('events.urls')),
    path('bookings/', include('bookings.urls')),
    path('polls/', include('polls.urls')),
    path('expenses/', include('expenses.urls')),
    path('backups/', include('backups.urls')),
    path('transfers/', include('transfers.urls')),
    path('member/', RedirectView.as_view(pattern_name='portal:login', permanent=False)),


    path('', include('accounts.urls')),
    path('django-admin/', admin.site.urls),
]
