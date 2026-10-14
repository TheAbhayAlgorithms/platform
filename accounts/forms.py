import re
from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from accounts.models import UserProfile, RoleChoices
from core.encryption import normalize_phone

class AdminLoginForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'Enter your username', 'autofocus': True})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Enter your password'}),
        required=True
    )


class OTPVerifyForm(forms.Form):
    otp_code = forms.CharField(
        max_length=6,
        min_length=6,
        required=True,
        widget=forms.TextInput(attrs={
            'placeholder': '6-digit OTP',
            'pattern': '[0-9]{6}',
            'maxlength': '6',
            'autofocus': True,
            'autocomplete': 'one-time-code',
            'style': 'letter-spacing: 4px; font-size: 1.25rem; text-align: center; max-width: 200px;'
        })
    )

    def clean_otp_code(self):
        code = self.cleaned_data.get('otp_code', '').strip()
        if not re.fullmatch(r'\d{6}', code):
            raise ValidationError("Please enter a valid 6-digit numeric OTP.")
        return code


class PasswordChangeCustomForm(forms.Form):
    current_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Current password'}),
        required=True
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'New password (min 8 chars)'}),
        required=True
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Confirm new password'}),
        required=True
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        current_password = self.cleaned_data.get('current_password')
        if not self.user.check_password(current_password):
            raise ValidationError("The current password you entered is incorrect.")
        return current_password

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')

        if new_password and confirm_password:
            if new_password != confirm_password:
                self.add_error('confirm_password', "The two new passwords do not match.")
            else:
                validate_password(new_password, self.user)
        return cleaned_data


class ForgotPasswordForm(forms.Form):
    username_or_email = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'Username or registered email', 'autofocus': True})
    )


class ResetPasswordTokenForm(forms.Form):
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'New password (min 8 chars)'}),
        required=True
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Confirm new password'}),
        required=True
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')

        if new_password and confirm_password:
            if new_password != confirm_password:
                self.add_error('confirm_password', "The two passwords do not match.")
            else:
                validate_password(new_password, self.user)
        return cleaned_data


class AdminUserCreateForm(forms.Form):
    username = forms.CharField(max_length=150, required=True)
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=True)
    role = forms.ChoiceField(choices=RoleChoices.choices, required=True)
    phone = forms.CharField(
        max_length=15,
        required=True,
        help_text="10-digit Indian mobile number for 2FA OTP delivery"
    )
    initial_password = forms.CharField(
        widget=forms.PasswordInput,
        required=True,
        help_text="Temporary password (min 8 characters)"
    )

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError(f"Username '{username}' already exists.")
        return username

    def clean_phone(self):
        phone_input = self.cleaned_data['phone'].strip()
        try:
            return normalize_phone(phone_input)
        except ValidationError as e:
            raise ValidationError(str(e))

    def clean_initial_password(self):
        pw = self.cleaned_data['initial_password']
        validate_password(pw)
        return pw


class AdminUserEditForm(forms.Form):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=True)
    role = forms.ChoiceField(choices=RoleChoices.choices, required=True)
    phone = forms.CharField(max_length=15, required=True)
    is_active = forms.BooleanField(required=False, initial=True)

    def __init__(self, user_instance, *args, **kwargs):
        self.user_instance = user_instance
        super().__init__(*args, **kwargs)

    def clean_phone(self):
        phone_input = self.cleaned_data['phone'].strip()
        try:
            return normalize_phone(phone_input)
        except ValidationError as e:
            raise ValidationError(str(e))


class AdminResetUserPasswordForm(forms.Form):
    new_password = forms.CharField(
        widget=forms.PasswordInput,
        required=True,
        help_text="New temporary password for this user"
    )

    def clean_new_password(self):
        pw = self.cleaned_data['new_password']
        validate_password(pw)
        return pw
