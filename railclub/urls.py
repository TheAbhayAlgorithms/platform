"""
URL configuration for RailClub Connect project.
"""
from django.contrib import admin
from django.urls import path
from core.views import home, health_check

urlpatterns = [
    path('', home, name='home'),
    path('health/', health_check, name='health_check'),
    path('django-admin/', admin.site.urls),
]
