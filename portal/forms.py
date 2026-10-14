from django import forms
from django.core.exceptions import ValidationError
from core.encryption import normalize_phone


class MemberPhoneLoginForm(forms.Form):
    """Form for initial member phone login entry."""
    phone = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter 10-digit mobile number (e.g. 9876543210)',
            'autocomplete': 'tel',
            'autofocus': True,
            'inputmode': 'numeric',
            'pattern': '[0-9+ ]*',
        }),
        help_text="Enter the Indian mobile number registered with your Railway Institute membership."
    )

    def clean_phone(self):
        raw_phone = self.cleaned_data.get('phone')
        try:
            return normalize_phone(raw_phone)
        except ValidationError:
            raise forms.ValidationError("Please enter a valid 10-digit Indian mobile number.")


class MemberOTPVerifyForm(forms.Form):
    """Form for 6-digit OTP verification."""
    otp = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '6-digit OTP',
            'autocomplete': 'one-time-code',
            'autofocus': True,
            'inputmode': 'numeric',
            'pattern': '[0-9]{6}',
            'style': 'letter-spacing: 0.3em; font-size: 1.25rem; text-align: center;',
        }),
        help_text="Enter the 6-digit verification code sent to your registered mobile number."
    )

    def clean_otp(self):
        otp = self.cleaned_data.get('otp', '').strip()
        if not otp.isdigit() or len(otp) != 6:
            raise forms.ValidationError("OTP must be exactly 6 digits.")
        return otp
