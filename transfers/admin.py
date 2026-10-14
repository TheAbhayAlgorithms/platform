from django.contrib import admin
from .models import Branch, InterDivisionalTransfer


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'division', 'zone', 'city', 'is_home_branch', 'is_active')
    list_filter = ('zone', 'is_home_branch', 'is_active')
    search_fields = ('code', 'name', 'division', 'zone', 'city')
    ordering = ('-is_home_branch', 'name')


@admin.register(InterDivisionalTransfer)
class InterDivisionalTransferAdmin(admin.ModelAdmin):
    list_display = ('transfer_id', 'member', 'from_branch', 'to_branch', 'transfer_type', 'status', 'dues_cleared', 'noc_number', 'effective_date')
    list_filter = ('status', 'transfer_type', 'dues_cleared')
    search_fields = ('transfer_id', 'member__name', 'transfer_order_number', 'noc_number')
    readonly_fields = ('transfer_id', 'noc_number', 'noc_issued_at', 'created_at', 'updated_at')
