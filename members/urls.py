from django.urls import path
from members import views

app_name = 'members'

urlpatterns = [
    path('', views.member_list_view, name='member_list'),
    path('add/', views.member_create_view, name='member_create'),
    path('import/', views.member_bulk_import_view, name='member_import'),
    path('<int:member_id>/', views.member_detail_view, name='member_detail'),
    path('<int:member_id>/edit/', views.member_edit_view, name='member_edit'),
    path('<int:member_id>/delete/', views.member_soft_delete_view, name='member_delete'),
    path('<int:member_id>/restore/', views.member_restore_view, name='member_restore'),
    path('<int:member_id>/family/add/', views.member_family_add_view, name='member_family_add'),
    path('<int:member_id>/family/<int:family_id>/delete/', views.member_family_delete_view, name='member_family_delete'),
]
