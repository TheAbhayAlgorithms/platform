from django.contrib import admin
from expenses.models import BudgetHead, Expense


@admin.register(BudgetHead)
class BudgetHeadAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'fiscal_year', 'allocated_amount', 'total_spent', 'remaining_amount', 'is_active')
    list_filter = ('fiscal_year', 'category', 'is_active')
    search_fields = ('name', 'notes')


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('voucher_number', 'title', 'payee', 'amount', 'category', 'expense_date', 'status', 'payment_mode')
    list_filter = ('status', 'category', 'payment_mode', 'expense_date')
    search_fields = ('voucher_number', 'title', 'payee', 'reference_number')
    date_hierarchy = 'expense_date'
