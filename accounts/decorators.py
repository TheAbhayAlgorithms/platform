from functools import wraps
from django.shortcuts import redirect
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django.urls import reverse
from accounts.models import RoleChoices

def admin_login_required(view_func):
    """
    Decorator requiring the user to be authenticated and an active staff user.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            login_url = reverse('accounts:login')
            return redirect(f"{login_url}?next={request.path}")
        if not request.user.is_active:
            messages.error(request, "Your account has been deactivated. Contact an administrator.")
            return redirect('accounts:login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def role_required(allowed_roles):
    """
    Decorator restricting view access to specific roles.
    Raises PermissionDenied (HTTP 403) if unauthorized.
    """
    if isinstance(allowed_roles, (str, RoleChoices)):
        allowed_roles = [str(allowed_roles)]
    else:
        allowed_roles = [str(r) for r in allowed_roles]

    def decorator(view_func):
        @wraps(view_func)
        @admin_login_required
        def _wrapped_view(request, *args, **kwargs):
            profile = getattr(request.user, 'profile', None)
            if not profile:
                raise PermissionDenied("Access Denied: No role profile found for this account.")

            # Super admin always has access unless explicitly restricted
            if profile.role in allowed_roles or profile.is_super_admin:
                return view_func(request, *args, **kwargs)

            raise PermissionDenied(
                f"Access Denied: Your role ({profile.get_role_display()}) does not have permission for this section."
            )
        return _wrapped_view
    return decorator


def super_admin_required(view_func):
    return role_required([RoleChoices.SUPER_ADMIN])(view_func)

def payment_management_required(view_func):
    return role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ACCOUNTANT])(view_func)

def event_management_required(view_func):
    return role_required([RoleChoices.SUPER_ADMIN, RoleChoices.EVENT_MANAGER])(view_func)
