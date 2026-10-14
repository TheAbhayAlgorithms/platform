from django import forms
from plans.models import Plan, DiscountConcession


class MemberRenewalForm(forms.Form):
    """
    Form to execute a renewal for a member.
    Allows choosing a different plan or discount concession.
    """
    plan = forms.ModelChoiceField(
        queryset=Plan.objects.filter(is_active=True),
        empty_label=None,
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text="Select plan for the renewed cycle (defaults to current plan)."
    )
    discount = forms.ModelChoiceField(
        queryset=DiscountConcession.objects.filter(is_active=True),
        required=False,
        empty_label="-- No Discount / Standard Fee --",
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text="Optional concession applied to this renewal cycle."
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Optional renewal remarks or approval references...'
        }),
        help_text="Audit remarks for this renewal."
    )

    def __init__(self, *args, current_plan=None, **kwargs):
        super().__init__(*args, **kwargs)
        if current_plan and current_plan.is_active:
            self.fields['plan'].initial = current_plan
