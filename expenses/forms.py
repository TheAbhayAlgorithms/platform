from django import forms
from decimal import Decimal
from expenses.models import (
    Expense,
    BudgetHead,
    ExpenseCategory,
    ExpensePaymentMode,
    ExpenseStatus,
)


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = [
            'title', 'category', 'budget_head', 'payee', 'amount',
            'expense_date', 'payment_mode', 'reference_number', 'notes'
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Electrical rewiring & LED fixtures'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'budget_head': forms.Select(attrs={'class': 'form-control'}),
            'payee': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Vendor name or Contractor'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'expense_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'payment_mode': forms.Select(attrs={'class': 'form-control'}),
            'reference_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Bill / UTR / Cheque number'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Itemized details, bills, justification...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['budget_head'].queryset = BudgetHead.objects.filter(is_active=True).order_by('-fiscal_year', 'name')
        self.fields['budget_head'].required = False


class BudgetHeadForm(forms.ModelForm):
    class Meta:
        model = BudgetHead
        fields = [
            'name', 'category', 'fiscal_year', 'allocated_amount', 'notes', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Annual Sports & Gym Budget'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'fiscal_year': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '2026-2027'}),
            'allocated_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Approval resolution, sanctioned committee meeting date...'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class ExpenseRejectionForm(forms.Form):
    rejection_reason = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Explain why this expenditure voucher is rejected...'})
    )
