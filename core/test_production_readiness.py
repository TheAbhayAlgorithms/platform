import json
import pytest
from django.urls import reverse
from django.test import RequestFactory
from django.contrib.auth.models import User
from accounts.models import UserProfile, RoleChoices
from core.views import (
    health_check,
    system_health_dashboard,
    custom_page_not_found_view,
    custom_server_error_view
)
from core.services import get_system_health_status


@pytest.fixture
def super_admin_user(db):
    user = User.objects.create_user(username='admin_prod', email='admin_prod@railclub.in', password='password123')
    UserProfile.objects.create(user=user, role=RoleChoices.SUPER_ADMIN, phone='+919876543201')
    return user


@pytest.fixture
def accountant_user(db):
    user = User.objects.create_user(username='acct_prod', email='acct_prod@railclub.in', password='password123')
    UserProfile.objects.create(user=user, role=RoleChoices.ACCOUNTANT, phone='+919876543202')
    return user


@pytest.mark.django_db
def test_system_health_diagnostics_service():
    diagnostics = get_system_health_status()
    assert diagnostics['status'] == 'HEALTHY'
    assert diagnostics['version'] == '1.0.0'
    assert 'database' in diagnostics['subsystems']
    assert diagnostics['subsystems']['database']['status'] == 'OK'
    assert 'encryption' in diagnostics['subsystems']
    assert diagnostics['subsystems']['encryption']['status'] == 'OK'
    assert 'storage' in diagnostics['subsystems']
    assert diagnostics['subsystems']['storage']['status'] == 'OK'
    assert 'whatsapp_engine' in diagnostics['subsystems']


@pytest.mark.django_db
def test_health_check_http_endpoint(client):
    response = client.get(reverse('health_check'))
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'ok'
    assert data['app'] == 'RailClub Connect'

    full_resp = client.get(reverse('health_check') + '?full=1')
    assert full_resp.status_code == 200
    full_data = full_resp.json()
    assert full_data['status'] == 'HEALTHY'
    assert full_data['subsystems']['database']['status'] == 'OK'


@pytest.mark.django_db
def test_system_health_dashboard_access_rbac(client, super_admin_user, accountant_user):
    # Unauthenticated redirects to login
    response = client.get(reverse('system_health'))
    assert response.status_code == 302
    assert '/login/' in response.url

    # Accountant access denied (Super Admin only)
    client.force_login(accountant_user)
    response = client.get(reverse('system_health'))
    assert response.status_code == 403

    # Super Admin allowed
    client.force_login(super_admin_user)
    response = client.get(reverse('system_health'))
    assert response.status_code == 200
    assert "System Health" in response.content.decode()
    assert "Runtime Readiness" in response.content.decode()


@pytest.mark.django_db
def test_custom_404_view():
    factory = RequestFactory()
    request = factory.get('/non-existent-route-for-testing/')
    response = custom_page_not_found_view(request)
    assert response.status_code == 404
    content = response.content.decode()
    assert "Platform Route Not Found" in content
    assert "404" in content


@pytest.mark.django_db
def test_custom_500_view():
    factory = RequestFactory()
    request = factory.get('/error-test/')
    response = custom_server_error_view(request)
    assert response.status_code == 500
    content = response.content.decode()
    assert "System Processing Error" in content
    assert "500" in content


@pytest.mark.django_db
def test_production_security_headers(client):
    response = client.get(reverse('home'))
    assert response.status_code == 200
    headers = response.headers
    assert headers.get('X-Content-Type-Options') == 'nosniff'
    assert headers.get('X-Frame-Options') == 'SAMEORIGIN'


@pytest.mark.django_db
def test_master_setup_command():
    from django.core.management import call_command
    # Run setup_system without crashing
    call_command('setup_system')
