from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from plans.models import Plan, DiscountConcession, MemberPlanAssignment

class PlanForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = [
            'name',
            'description',
            'fee',
            'duration_months',
            'duration_days',
            'grace_period_days',
            'late_fee_type',
            'late_fee_amount',
            'is_active',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Describe member benefits and event entitlements.'}),
        }

    def clean_fee(self):
        fee = self.cleaned_data['fee']
        if fee < 0:
            raise ValidationError("Membership fee cannot be negative.")
        return fee

    def clean_late_fee_amount(self):
        amount = self.cleaned_data['late_fee_amount']
        if amount < 0:
            raise ValidationError("Late fee amount cannot be negative.")
        return amount


class DiscountConcessionForm(forms.ModelForm):
    class Meta:
        model = DiscountConcession
        fields = ['name', 'description', 'discount_type', 'discount_value', 'is_active']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
        }

    def clean_discount_value(self):
        val = self.cleaned_data['discount_value']
        dtype = self.cleaned_data.get('discount_type')
        if val < 0:
            raise ValidationError("Discount value cannot be negative.")
        if dtype == 'PERCENTAGE' and val > 100:
            raise ValidationError("Percentage discount cannot exceed 100%.")
        return val


class MemberPlanAssignForm(forms.ModelForm):
    class Meta:
        model = MemberPlanAssignment
        fields = ['plan', 'start_date', 'discount', 'notes']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Show only active plans and discounts
        self.fields['plan'].queryset = Plan.objects.filter(is_active=True)
        self.fields['discount'].queryset = DiscountConcession.objects.filter(is_active=True)
        self.fields['discount'].required = False

    def clean_plan(self):
        plan = self.cleaned_data.get('plan')
        if plan and not plan.is_active:
            raise ValidationError(f"Plan '{plan.name}' is deactivated and cannot be newly assigned.")
        return plan
