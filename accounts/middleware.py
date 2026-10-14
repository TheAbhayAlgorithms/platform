import time
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse

class SessionIdleTimeoutMiddleware:
    """
    Enforces strict idle session timeout (default 20 minutes) for authenticated users.
    Logs out the user and redirects to login if idle duration is exceeded.
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self.timeout_seconds = getattr(settings, 'ADMIN_SESSION_TIMEOUT_SECONDS', 20 * 60)

    def __call__(self, request):
        if request.user.is_authenticated:
            current_time = int(time.time())
            last_activity = request.session.get('last_activity')

            if last_activity and (current_time - last_activity > self.timeout_seconds):
                logout(request)
                messages.warning(
                    request,
                    "Your session has expired due to 20 minutes of inactivity. Please log in again."
                )
                login_url = reverse('accounts:login')
                return redirect(f"{login_url}?next={request.path}")

            request.session['last_activity'] = current_time

        response = self.get_response(request)
        return response
