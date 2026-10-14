from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse
from members.models import Member


def member_login_required(view_func):
    """
    Decorator to restrict access to authenticated members in the Member Portal.
    Validates member session and attaches `request.portal_member`.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        is_authenticated = request.session.get('member_authenticated', False)
        member_id = request.session.get('member_id')

        if not is_authenticated or not member_id:
            messages.info(request, "Please enter your registered mobile number and OTP to view your membership.")
            return redirect('portal:login')

        member = Member.objects.active_records().filter(pk=member_id).first()
        if not member:
            request.session.flush()
            messages.error(request, "Member record not found or no longer active. Please contact the Institute.")
            return redirect('portal:login')

        request.portal_member = member
        return view_func(request, *args, **kwargs)

    return _wrapped_view
