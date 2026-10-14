from django.urls import path
from renewals import views

app_name = 'renewals'

urlpatterns = [
    path('', views.renewal_list, name='renewal_list'),
    path('member/<int:member_id>/renew/', views.renew_member, name='renew_member'),
    path('member/<int:member_id>/one-click-renew/', views.one_click_renew, name='one_click_renew'),
    path('member/<int:member_id>/history/', views.member_renewal_history, name='member_history'),
    path('auto-expire/', views.run_auto_expiry_sweep, name='run_auto_expiry'),
]
