from django.urls import path
from . import views

app_name = 'transfers'

urlpatterns = [
    path('', views.transfer_list, name='list'),
    path('new/', views.transfer_create, name='create'),
    path('branches/', views.branch_list, name='branches'),
    path('<str:transfer_id>/', views.transfer_detail, name='detail'),
    path('<str:transfer_id>/approve/', views.transfer_approve, name='approve'),
    path('<str:transfer_id>/reject/', views.transfer_reject, name='reject'),
    path('<str:transfer_id>/complete/', views.transfer_complete, name='complete'),
    path('<str:transfer_id>/noc/', views.transfer_noc_view, name='noc'),
]
