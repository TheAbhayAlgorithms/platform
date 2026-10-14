from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from members.models import Member, MemberFamily, MemberStatus, DepartmentChoices
from core.encryption import normalize_phone, compute_blind_index

class MemberForm(forms.ModelForm):
    phone = forms.CharField(
        max_length=15,
        required=True,
        help_text="10-digit Indian mobile number (e.g., 9876543210)"
    )

    class Meta:
        model = Member
        fields = [
            'name',
            'phone',
            'employee_id',
            'department',
            'address',
            'date_joined',
            'status',
            'whatsapp_opt_in',
            'notes',
        ]
        widgets = {
            'date_joined': forms.DateInput(attrs={'type': 'date'}),
            'address': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def clean_phone(self):
        phone_val = self.cleaned_data['phone'].strip()
        try:
            normalized = normalize_phone(phone_val)
        except ValidationError as e:
            raise ValidationError(str(e))

        blind_idx = compute_blind_index(normalized)
        # Check duplicate
        qs = Member.objects.filter(phone_blind_index=blind_idx, is_removed=False)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            existing = qs.first()
            raise ValidationError(
                f"Phone number {normalized} is already registered to member: {existing.name} ({existing.membership_id})."
            )

        return normalized


class MemberFamilyForm(forms.ModelForm):
    class Meta:
        model = MemberFamily
        fields = ['name', 'relationship', 'date_of_birth', 'phone', 'notes']
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}),
        }


class MemberRemoveForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'State mandatory reason for removing this member (e.g. non-payment, retirement, resignation)'}),
        required=True,
        help_text="Mandatory audit justification for soft-deleting this member record."
    )


class MemberBulkImportForm(forms.Form):
    file = forms.FileField(
        required=True,
        help_text="Upload an Excel file (.xlsx) or CSV file (.csv) containing member records."
    )
    dry_run = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Check to validate and preview without modifying the database."
    )

    def clean_file(self):
        f = self.cleaned_data['file']
        ext = f.name.split('.')[-1].lower()
        if ext not in ['csv', 'xlsx']:
            raise ValidationError("Unsupported file format. Please upload a .csv or .xlsx file.")
        if f.size > 10 * 1024 * 1024:
            raise ValidationError("File size exceeds 10MB limit.")
        return f
