from django.urls import path
from expenses import views

app_name = 'expenses'

urlpatterns = [
    # Expense Vouchers
    path('', views.expense_list, name='expense_list'),
    path('new/', views.expense_create, name='expense_create'),
    path('<int:expense_id>/', views.expense_detail, name='expense_detail'),
    path('<int:expense_id>/approve/', views.expense_approve, name='expense_approve'),
    path('<int:expense_id>/reject/', views.expense_reject, name='expense_reject'),
    path('export/', views.expense_export_csv, name='expense_export_csv'),

    # Fiscal Year Budget Allocations
    path('budgets/', views.budget_list, name='budget_list'),
    path('budgets/new/', views.budget_create, name='budget_create'),
    path('budgets/<int:budget_id>/edit/', views.budget_edit, name='budget_edit'),
]
