from django.urls import path
from bookings import views

app_name = 'bookings'

urlpatterns = [
    # Staff Booking Management
    path('', views.booking_list, name='booking_list'),
    path('new/', views.booking_create, name='booking_create'),
    path('<int:booking_id>/', views.booking_detail, name='booking_detail'),
    path('<int:booking_id>/approve/', views.booking_approve, name='booking_approve'),
    path('<int:booking_id>/cancel/', views.booking_cancel, name='booking_cancel'),
    path('<int:booking_id>/refund-deposit/', views.booking_refund_deposit, name='booking_refund_deposit'),

    # Facility Management
    path('facilities/', views.facility_list, name='facility_list'),
    path('facilities/new/', views.facility_create, name='facility_create'),
    path('facilities/<int:facility_id>/edit/', views.facility_edit, name='facility_edit'),

    # Member Portal routes
    path('portal/', views.portal_booking_list, name='portal_bookings'),
    path('portal/request/', views.portal_booking_request, name='portal_request'),
    path('portal/<int:booking_id>/cancel/', views.portal_booking_cancel, name='portal_cancel'),
]
