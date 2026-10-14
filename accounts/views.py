import re
import time
import logging
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.urls import reverse
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from accounts.models import UserProfile, RoleChoices, AdminOTP
from accounts.forms import (
    AdminLoginForm,
    OTPVerifyForm,
    PasswordChangeCustomForm,
    ForgotPasswordForm,
    ResetPasswordTokenForm,
    AdminUserCreateForm,
    AdminUserEditForm,
    AdminResetUserPasswordForm,
)
from accounts.decorators import admin_login_required, super_admin_required
from core.messaging import get_whatsapp_provider

logger = logging.getLogger(__name__)

def admin_login_view(request):
    """
    Step 1 of Admin Authentication:
    Validates username and password, enforces brute-force lockout,
    and initiates 2FA OTP delivery.
    """
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        form = AdminLoginForm(request.POST)
        if form.is_valid():
            login_input = form.cleaned_data['username'].strip()
            password = form.cleaned_data['password']

            # Support login by username, email, or registered phone number
            clean_digits = re.sub(r'\D', '', login_input)
            user = None
            if clean_digits and len(clean_digits) >= 10:
                user = User.objects.filter(profile__phone__endswith=clean_digits[-10:]).first()
            if not user:
                user = User.objects.filter(username__iexact=login_input).first() or User.objects.filter(email__iexact=login_input).first()

            profile = getattr(user, 'profile', None) if user else None
            if user and not profile:
                profile, _ = UserProfile.objects.get_or_create(user=user)

            # Check lockout
            if profile and profile.is_locked_out():
                remaining_mins = max(1, profile.get_remaining_lockout_seconds() // 60)
                messages.error(
                    request,
                    f"Account is temporarily locked due to 5 consecutive failed login attempts. "
                    f"Please try again in {remaining_mins} minutes."
                )
                return render(request, 'accounts/login.html', {'form': form})

            # Check if user is disabled
            if user and not user.is_active and user.check_password(password):
                messages.error(request, "This account has been disabled. Please contact an administrator.")
                return render(request, 'accounts/login.html', {'form': form})

            # Authenticate credentials using the user's canonical username
            auth_username = user.username if user else login_input
            authenticated_user = authenticate(request, username=auth_username, password=password)

            if authenticated_user is not None:
                # Check 2FA
                if profile and profile.is_2fa_enabled:
                    otp_code = AdminOTP.create_for_user(authenticated_user, purpose='login')
                    phone = profile.phone or "admin-phone"
                    
                    provider = get_whatsapp_provider()
                    provider.send_otp(phone, otp_code)

                    request.session['pending_2fa_user_id'] = authenticated_user.id
                    request.session['pending_2fa_next'] = request.GET.get('next', '')
                    request.session['demo_otp'] = otp_code
                    
                    messages.info(request, "A 6-digit verification code has been dispatched.")
                    return redirect('accounts:verify_otp')
                else:
                    # Direct login if 2FA disabled
                    login(request, authenticated_user)
                    if profile:
                        profile.reset_failed_attempts()
                    request.session['last_activity'] = int(time.time())
                    next_url = request.GET.get('next') or reverse('accounts:dashboard')
                    return redirect(next_url)
            else:
                if profile:
                    profile.record_failed_attempt()
                    if profile.is_locked_out():
                        messages.error(
                            request,
                            "Maximum failed login attempts reached (5). "
                            "Your account is now locked for 15 minutes."
                        )
                    else:
                        remaining = 5 - profile.failed_login_attempts
                        messages.error(
                            request,
                            f"Invalid credentials. You have {remaining} attempt(s) remaining before lockout."
                        )
                else:
                    messages.error(request, "Invalid credentials. Please verify your username/email/phone and password.")
    else:
        form = AdminLoginForm()

    return render(request, 'accounts/login.html', {'form': form})


def admin_verify_otp_view(request):
    """
    Step 2 of Admin Authentication:
    Verifies 6-digit single-use OTP, completes login, and resets lockout counters.
    """
    user_id = request.session.get('pending_2fa_user_id')
    if not user_id:
        return redirect('accounts:login')

    user = get_object_or_404(User, id=user_id)
    profile = getattr(user, 'profile', None)

    # Mask phone number for display (e.g., +91 ******4321)
    raw_phone = profile.phone if profile and profile.phone else ""
    if len(raw_phone) >= 4:
        masked_phone = raw_phone[:3] + " " + "*" * (len(raw_phone) - 7) + raw_phone[-4:]
    else:
        masked_phone = "registered mobile"

    if request.method == 'POST':
        form = OTPVerifyForm(request.POST)
        if form.is_valid():
            otp_code = form.cleaned_data['otp_code']
            
            # Find the active unexpired OTP
            latest_otp = AdminOTP.objects.filter(
                user=user,
                purpose='login',
                is_used=False,
                expires_at__gt=timezone.now()
            ).order_by('-created_at').first()

            if latest_otp and latest_otp.verify(otp_code):
                # Successful 2FA verification
                login(request, user)
                if profile:
                    profile.reset_failed_attempts()
                
                # Cleanup 2FA session variables
                next_url = request.session.get('pending_2fa_next') or reverse('accounts:dashboard')
                request.session.pop('pending_2fa_user_id', None)
                request.session.pop('pending_2fa_next', None)
                request.session.pop('demo_otp', None)

                request.session['last_activity'] = int(time.time())
                messages.success(request, f"Welcome back, {user.first_name or user.username}!")
                return redirect(next_url)
            else:
                form.add_error('otp_code', "Invalid or expired OTP. Please re-check or request a new code.")
    else:
        form = OTPVerifyForm()

    demo_otp = request.session.get('demo_otp') if (getattr(settings, 'WHATSAPP_PROVIDER', 'mock') == 'mock' or settings.DEBUG) else None

    return render(request, 'accounts/verify_otp.html', {
        'form': form,
        'masked_phone': masked_phone,
        'demo_otp': demo_otp,
    })


def admin_resend_otp_view(request):
    """Resend 2FA OTP to the pending user."""
    user_id = request.session.get('pending_2fa_user_id')
    if not user_id:
        return redirect('accounts:login')

    user = get_object_or_404(User, id=user_id)
    profile = getattr(user, 'profile', None)

    otp_code = AdminOTP.create_for_user(user, purpose='login')
    phone = profile.phone if profile and profile.phone else "admin-phone"
    
    provider = get_whatsapp_provider()
    provider.send_otp(phone, otp_code)

    request.session['demo_otp'] = otp_code
    messages.info(request, "A fresh verification code has been dispatched to your mobile number.")
    return redirect('accounts:verify_otp')


def admin_logout_view(request):
    """Logs out the current admin and clears the session."""
    logout(request)
    messages.info(request, "You have been logged out securely.")
    return redirect('accounts:login')


@admin_login_required
def admin_dashboard_view(request):
    """Admin portal main dashboard showing role-specific information."""
    profile = getattr(request.user, 'profile', None)
    return render(request, 'accounts/dashboard.html', {
        'profile': profile,
    })


@admin_login_required
def change_password_view(request):
    """Allows an authenticated admin to change their own password."""
    if request.method == 'POST':
        form = PasswordChangeCustomForm(request.user, request.POST)
        if form.is_valid():
            new_password = form.cleaned_data['new_password']
            request.user.set_password(new_password)
            request.user.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, "Your password has been updated successfully.")
            return redirect('accounts:dashboard')
    else:
        form = PasswordChangeCustomForm(request.user)

    return render(request, 'accounts/change_password.html', {'form': form})


def forgot_password_view(request):
    """
    Sends a secure password reset link token.
    In mock/dev mode, logs link to console.
    """
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            identifier = form.cleaned_data['username_or_email'].strip()
            user = User.objects.filter(username__iexact=identifier).first()
            if not user:
                user = User.objects.filter(email__iexact=identifier).first()

            if user and user.is_active:
                token = default_token_generator.make_token(user)
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                reset_url = request.build_absolute_uri(
                    reverse('accounts:reset_password_confirm', kwargs={'uidb64': uid, 'token': token})
                )
                logger.info(f"[PASSWORD RESET LINK] User: {user.username} -> {reset_url}")
                print(f"\n[PASSWORD RESET LINK] For {user.username}: {reset_url}\n")
            
            # Always show the same generic message to prevent username/email enumeration
            messages.info(
                request,
                "If the account exists and is active, a password reset link has been dispatched."
            )
            return redirect('accounts:login')
    else:
        form = ForgotPasswordForm()

    return render(request, 'accounts/forgot_password.html', {'form': form})


def reset_password_confirm_view(request, uidb64, token):
    """Verifies reset token and sets new password."""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is None or not default_token_generator.check_token(user, token):
        messages.error(request, "This password reset link is invalid or has expired.")
        return redirect('accounts:forgot_password')

    if request.method == 'POST':
        form = ResetPasswordTokenForm(user, request.POST)
        if form.is_valid():
            new_password = form.cleaned_data['new_password']
            user.set_password(new_password)
            user.save()
            messages.success(request, "Password has been reset successfully. Please log in.")
            return redirect('accounts:login')
    else:
        form = ResetPasswordTokenForm(user)

    return render(request, 'accounts/reset_password_confirm.html', {'form': form})


# ==========================================================
# ADMIN USER MANAGEMENT (Super Admin Only)
# ==========================================================

@super_admin_required
def admin_user_list_view(request):
    """Lists all admin users, roles, phone, and status."""
    users = User.objects.select_related('profile').all().order_by('-date_joined')
    return render(request, 'accounts/user_list.html', {'admin_users': users})


@super_admin_required
def admin_user_create_view(request):
    """Creates a new administrative user with assigned role and credentials."""
    if request.method == 'POST':
        form = AdminUserCreateForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            email = form.cleaned_data['email']
            first_name = form.cleaned_data['first_name']
            last_name = form.cleaned_data['last_name']
            role = form.cleaned_data['role']
            phone = form.cleaned_data['phone']
            initial_password = form.cleaned_data['initial_password']

            new_user = User.objects.create_user(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=initial_password,
                is_staff=True,
            )

            UserProfile.objects.create(
                user=new_user,
                role=role,
                phone=phone,
                is_2fa_enabled=True,
            )

            messages.success(request, f"Admin user '{username}' created successfully.")
            return redirect('accounts:user_list')
    else:
        form = AdminUserCreateForm()

    return render(request, 'accounts/user_form.html', {
        'form': form,
        'title': 'Create New Admin User',
    })


@super_admin_required
def admin_user_edit_view(request, user_id):
    """Edits an admin user's details, role, phone, and active status."""
    target_user = get_object_or_404(User, id=user_id)
    profile, _ = UserProfile.objects.get_or_create(user=target_user)

    if request.method == 'POST':
        form = AdminUserEditForm(target_user, request.POST)
        if form.is_valid():
            # Prevent super admin from accidentally deactivating themselves
            if target_user == request.user and not form.cleaned_data['is_active']:
                messages.error(request, "You cannot deactivate your own administrative account.")
                return redirect('accounts:user_list')

            target_user.first_name = form.cleaned_data['first_name']
            target_user.last_name = form.cleaned_data['last_name']
            target_user.email = form.cleaned_data['email']
            target_user.is_active = form.cleaned_data['is_active']
            target_user.save()

            profile.role = form.cleaned_data['role']
            profile.phone = form.cleaned_data['phone']
            profile.save()

            messages.success(request, f"Admin user '{target_user.username}' updated successfully.")
            return redirect('accounts:user_list')
    else:
        initial_data = {
            'first_name': target_user.first_name,
            'last_name': target_user.last_name,
            'email': target_user.email,
            'role': profile.role,
            'phone': profile.phone or '',
            'is_active': target_user.is_active,
        }
        form = AdminUserEditForm(target_user, initial=initial_data)

    return render(request, 'accounts/user_form.html', {
        'form': form,
        'title': f"Edit Admin User: {target_user.username}",
        'target_user': target_user,
    })


@super_admin_required
def admin_user_toggle_status_view(request, user_id):
    """Toggles active/disabled status for an admin user."""
    target_user = get_object_or_404(User, id=user_id)
    if target_user == request.user:
        messages.error(request, "You cannot toggle active status on your own account.")
        return redirect('accounts:user_list')

    target_user.is_active = not target_user.is_active
    target_user.save()

    status_str = "activated" if target_user.is_active else "deactivated"
    messages.success(request, f"User '{target_user.username}' has been {status_str}.")
    return redirect('accounts:user_list')


@super_admin_required
def admin_user_reset_password_view(request, user_id):
    """Allows Super Admin to forcefully set a new password for an admin user."""
    target_user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        form = AdminResetUserPasswordForm(request.POST)
        if form.is_valid():
            new_password = form.cleaned_data['new_password']
            target_user.set_password(new_password)
            target_user.save()
            messages.success(request, f"Password for '{target_user.username}' has been updated.")
            return redirect('accounts:user_list')
    else:
        form = AdminResetUserPasswordForm()

    return render(request, 'accounts/user_reset_password.html', {
        'form': form,
        'target_user': target_user,
    })
