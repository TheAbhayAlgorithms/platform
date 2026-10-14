from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from members.models import Member
from transfers.models import Branch, InterDivisionalTransfer, TransferType


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = [
            'name', 'code', 'zone', 'division', 'city', 'state',
            'contact_person', 'contact_phone', 'contact_email',
            'is_home_branch', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Delhi Main Railway Club'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. NR-DLI'}),
            'zone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Northern Railway'}),
            'division': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Delhi'}),
            'city': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. New Delhi'}),
            'state': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Delhi'}),
            'contact_person': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Secretary / Sr. DPO'}),
            'contact_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. +91 98765 43210'}),
            'contact_email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'e.g. club.delhi@railclub.in'}),
            'is_home_branch': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class TransferRequestForm(forms.ModelForm):
    class Meta:
        model = InterDivisionalTransfer
        fields = [
            'member', 'from_branch', 'to_branch', 'transfer_type',
            'transfer_order_number', 'transfer_order_date', 'effective_date', 'remarks'
        ]
        widgets = {
            'member': forms.Select(attrs={'class': 'form-select select2-member'}),
            'from_branch': forms.Select(attrs={'class': 'form-select'}),
            'to_branch': forms.Select(attrs={'class': 'form-select'}),
            'transfer_type': forms.Select(attrs={'class': 'form-select'}),
            'transfer_order_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. NR/P/EE/TR/2026/104'}),
            'transfer_order_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'effective_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'remarks': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Administrative reason, posting details, or special remarks.'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['member'].queryset = Member.objects.filter(is_removed=False).order_by('name')
        self.fields['from_branch'].queryset = Branch.objects.filter(is_active=True).order_by('-is_home_branch', 'name')
        self.fields['to_branch'].queryset = Branch.objects.filter(is_active=True).order_by('-is_home_branch', 'name')

        # Auto-select home branch as origin default for outgoing
        home = Branch.objects.filter(is_home_branch=True, is_active=True).first()
        if home and not self.initial.get('from_branch'):
            self.initial['from_branch'] = home.id

    def clean(self):
        cleaned_data = super().clean()
        from_b = cleaned_data.get('from_branch')
        to_b = cleaned_data.get('to_branch')
        member = cleaned_data.get('member')

        if from_b and to_b and from_b == to_b:
            raise ValidationError("Origin Branch and Destination Branch cannot be identical.")

        if member:
            existing = InterDivisionalTransfer.objects.filter(
                member=member,
                status='PENDING'
            )
            if self.instance and self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise ValidationError(f"Member '{member.name}' already has an active pending transfer request.")

        return cleaned_data


class TransferApprovalForm(forms.Form):
    admin_remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Optional approval remarks or conditions.'})
    )
    force_override = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label="Grant Authorized Clearance Override (if outstanding dues exist)"
    )


class TransferRejectionForm(forms.Form):
    rejection_reason = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Detailed grounds for declining transfer request (mandatory).'})
    )
