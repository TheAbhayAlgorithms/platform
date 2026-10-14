"""
URL configuration for RailClub Connect project.
"""
from django.contrib import admin
from django.urls import path, include
from core.views import home, health_check

urlpatterns = [
    path('', home, name='home'),
    path('health/', health_check, name='health_check'),
    path('payments/', include('payments.urls')),
    path('renewals/', include('renewals.urls')),
    path('plans/', include('plans.urls')),
    path('members/', include('members.urls')),
    path('', include('accounts.urls')),
    path('django-admin/', admin.site.urls),
]
