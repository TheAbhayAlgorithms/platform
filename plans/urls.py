from django.urls import path
from plans import views

app_name = 'plans'

urlpatterns = [
    path('', views.plan_list_view, name='plan_list'),
    path('add/', views.plan_create_view, name='plan_create'),
    path('<int:plan_id>/edit/', views.plan_edit_view, name='plan_edit'),
    path('<int:plan_id>/toggle/', views.plan_toggle_active_view, name='plan_toggle'),
    path('discounts/add/', views.discount_create_view, name='discount_create'),
    path('discounts/<int:discount_id>/toggle/', views.discount_toggle_active_view, name='discount_toggle'),
    path('assign/<int:member_id>/', views.member_assign_plan_view, name='member_assign'),
]
