from django.urls import path
from events import views

app_name = 'events'

urlpatterns = [
    # Staff / Admin routes
    path('', views.event_list, name='event_list'),
    path('create/', views.event_create, name='event_create'),
    path('<int:event_id>/', views.event_detail, name='event_detail'),
    path('<int:event_id>/edit/', views.event_edit, name='event_edit'),
    path('<int:event_id>/cancel/', views.event_cancel, name='event_cancel'),
    path('<int:event_id>/register/', views.event_register_member, name='event_register_member'),
    path('<int:event_id>/export/', views.event_export_attendees, name='event_export_attendees'),
    path('registration/<int:registration_id>/check-in/', views.event_check_in_toggle, name='event_check_in_toggle'),
    path('registration/<int:registration_id>/cancel/', views.event_cancel_registration, name='event_cancel_registration'),

    # Member Portal routes
    path('portal/', views.portal_event_list, name='portal_events'),
    path('portal/<int:event_id>/rsvp/', views.portal_event_rsvp, name='portal_rsvp'),
    path('portal/rsvp/<int:registration_id>/cancel/', views.portal_event_cancel_rsvp, name='portal_cancel_rsvp'),
]
