from django.urls import path
from accounts import views

app_name = 'accounts'

urlpatterns = [
    # Authentication & 2FA
    path('login/', views.admin_login_view, name='login'),
    path('login/verify-otp/', views.admin_verify_otp_view, name='verify_otp'),
    path('login/resend-otp/', views.admin_resend_otp_view, name='resend_otp'),
    path('logout/', views.admin_logout_view, name='logout'),
    path('password/change/', views.change_password_view, name='change_password'),
    path('password/forgot/', views.forgot_password_view, name='forgot_password'),
    path('password/reset/<uidb64>/<token>/', views.reset_password_confirm_view, name='reset_password_confirm'),

    # Admin Dashboard
    path('dashboard/', views.admin_dashboard_view, name='dashboard'),

    # Admin User Management (Super Admin only)
    path('users/', views.admin_user_list_view, name='user_list'),
    path('users/add/', views.admin_user_create_view, name='user_create'),
    path('users/<int:user_id>/edit/', views.admin_user_edit_view, name='user_edit'),
    path('users/<int:user_id>/toggle-status/', views.admin_user_toggle_status_view, name='user_toggle_status'),
    path('users/<int:user_id>/reset-password/', views.admin_user_reset_password_view, name='user_reset_password'),
]
