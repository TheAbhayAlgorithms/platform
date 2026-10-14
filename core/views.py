from django.shortcuts import render
from django.http import JsonResponse
from accounts.decorators import super_admin_required
from core.services import get_system_health_status


def home(request):
    """
    Public landing page for RailClub Connect.
    """
    return render(request, 'home.html')


def health_check(request):
    """
    Standard HTTP health check and readiness probe.
    Returns HTTP 200 with basic status and application name.
    If ?full=1 is supplied, returns full subsystem diagnostics telemetry.
    """
    diagnostics = get_system_health_status()
    is_healthy = diagnostics['status'] == 'HEALTHY'
    status_code = 200 if is_healthy else 503

    if request.GET.get('full') == '1':
        return JsonResponse(diagnostics, status=status_code)

    return JsonResponse({
        'status': 'ok' if is_healthy else 'degraded',
        'app': 'RailClub Connect'
    }, status=status_code)


@super_admin_required
def system_health_dashboard(request):
    """
    Staff diagnostic dashboard displaying live health metrics across database,
    encryption, file storage, and background notification subsystems.
    """
    diagnostics = get_system_health_status()
    return render(request, 'core/system_health.html', {
        'diagnostics': diagnostics
    })


def custom_page_not_found_view(request, exception=None):
    """
    Custom 404 handler with design system styling and navigation recovery links.
    """
    return render(request, '404.html', status=404)


def custom_server_error_view(request):
    """
    Custom 500 handler with incident notification and administrator support details.
    """
    return render(request, '500.html', status=500)
