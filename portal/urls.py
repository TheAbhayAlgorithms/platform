from django.urls import path
from portal import views

app_name = 'portal'

urlpatterns = [
    path('', views.member_login, name='login'),
    path('verify-otp/', views.member_verify_otp, name='verify_otp'),
    path('resend-otp/', views.member_resend_otp, name='resend_otp'),
    path('dashboard/', views.member_dashboard, name='dashboard'),
    path('receipt/<int:payment_id>/download/', views.member_download_receipt, name='download_receipt'),
    path('transfers/<str:transfer_id>/noc/', views.member_view_noc, name='download_noc'),
    path('logout/', views.member_logout, name='logout'),
]
