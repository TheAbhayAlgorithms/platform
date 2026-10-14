"""
URL configuration for RailClub Connect project.
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from core.views import home, health_check

urlpatterns = [
    path('', home, name='home'),
    path('health/', health_check, name='health_check'),
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
    path('member/', RedirectView.as_view(pattern_name='portal:login', permanent=False)),


    path('', include('accounts.urls')),
    path('django-admin/', admin.site.urls),
]
