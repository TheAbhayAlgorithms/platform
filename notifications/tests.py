import json
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock
import pytest
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User
from django.test import Client

from accounts.models import UserProfile, RoleChoices
from members.models import Member, MemberStatus, DepartmentChoices
from plans.models import Plan, MemberPlanAssignment
from payments.models import Payment, PaymentMode, PaymentStatus
from payments.services import record_payment
from notifications.models import (
    WhatsAppMessageLog,
    NotificationTemplate,
    NotificationStatus,
)
from notifications.providers.mock_provider import MockWhatsAppProvider
from notifications.providers.cloud_api_provider import CloudAPIWhatsAppProvider
from notifications.services import (
    get_whatsapp_provider,
    send_whatsapp_notification,
    process_whatsapp_webhook_payload,
    render_payment_receipt_message,
    render_renewal_upcoming_message,
    render_payment_due_message,
    render_membership_expired_message,
    render_otp_message,
)


@pytest.fixture(autouse=True)
def clear_mock_whatsapp():
    MockWhatsAppProvider.clear_sent_messages()
    yield
    MockWhatsAppProvider.clear_sent_messages()


@pytest.fixture
def superadmin_user(db):
    user = User.objects.create_user(username='wa_admin', password='AdminPassword@2026!')
    UserProfile.objects.create(user=user, role=RoleChoices.SUPER_ADMIN, phone='+919876543210')
    return user


@pytest.fixture
def accountant_user(db):
    user = User.objects.create_user(username='wa_acct', password='AcctPassword@2026!')
    UserProfile.objects.create(user=user, role=RoleChoices.ACCOUNTANT, phone='+919876543211')
    return user


@pytest.fixture
def viewer_user(db):
    user = User.objects.create_user(username='wa_view', password='ViewPassword@2026!')
    UserProfile.objects.create(user=user, role=RoleChoices.VIEWER, phone='+919876543213')
    return user


@pytest.fixture
def standard_plan(db):
    return Plan.objects.create(
        name="Annual Membership 2026",
        fee=Decimal('2400.00'),
        duration_months=12,
        grace_period_days=15,
        is_active=True
    )


@pytest.fixture
def optin_member(db, standard_plan):
    member = Member.objects.create(
        name="Kailash Sharma",
        phone="+919876533001",
        employee_id="WR-ENG-901",
        department=DepartmentChoices.ENGINEERING,
        status=MemberStatus.ACTIVE,
        whatsapp_opt_in=True
    )
    assignment = MemberPlanAssignment.objects.create(
        member=member,
        plan=standard_plan,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        base_fee=standard_plan.fee,
        is_current=True
    )
    return member


@pytest.fixture
def optout_member(db, standard_plan):
    member = Member.objects.create(
        name="Sunita Patil",
        phone="+919876533002",
        employee_id="CR-COM-902",
        department=DepartmentChoices.COMMERCIAL,
        status=MemberStatus.DUE,
        whatsapp_opt_in=False  # DPDP Opted out!
    )
    MemberPlanAssignment.objects.create(
        member=member,
        plan=standard_plan,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        base_fee=standard_plan.fee,
        is_current=True
    )
    return member


@pytest.mark.django_db
class TestWhatsAppProvidersAndDispatch:
    def test_mock_provider_message_dispatch(self, optin_member):
        """Mock provider dispatches and records WAMID and payload."""
        log = send_whatsapp_notification(
            member=optin_member,
            template_type=NotificationTemplate.PAYMENT_DUE
        )

        assert log.status == NotificationStatus.SENT
        assert log.external_message_id.startswith('wamid.mock.')
        assert log.sent_at is not None
        assert "7039145304" in log.message_body
        assert optin_member.name in log.message_body

        sent_list = MockWhatsAppProvider.get_sent_messages()
        assert len(sent_list) == 1
        assert sent_list[0]['recipient_phone'] == optin_member.phone
        assert sent_list[0]['wamid'] == log.external_message_id

    def test_dpdp_optout_enforcement(self, optout_member):
        """If member opted out, notification is blocked, logged as OPTED_OUT, and never sent."""
        log = send_whatsapp_notification(
            member=optout_member,
            template_type=NotificationTemplate.PAYMENT_DUE
        )

        assert log.status == NotificationStatus.OPTED_OUT
        assert "opted out" in log.error_message.lower()
        assert log.sent_at is None
        assert log.external_message_id == ""

        # Provider must NOT have been called
        sent_list = MockWhatsAppProvider.get_sent_messages()
        assert len(sent_list) == 0

    @patch('notifications.providers.cloud_api_provider.requests.post')
    def test_cloud_api_provider_successful_dispatch(self, mock_post, optin_member, settings):
        """Tests CloudAPI provider payload structure and response handling with Meta API."""
        settings.WHATSAPP_API_TOKEN = 'test_meta_token_12345'
        settings.WHATSAPP_PHONE_NUMBER_ID = '1000999888'

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'messaging_product': 'whatsapp',
            'contacts': [{'input': '919876533001', 'wa_id': '919876533001'}],
            'messages': [{'id': 'wamid.HBgLMTIzNDU2Nzg5AA=='}]
        }
        mock_post.return_value = mock_resp

        provider = CloudAPIWhatsAppProvider()
        success, wamid, err = provider.send_message(
            recipient_phone="+919876533001",
            message_text="Test Message"
        )

        assert success is True
        assert wamid == 'wamid.HBgLMTIzNDU2Nzg5AA=='
        assert err is None

        # Verify POST payload
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs['headers']['Authorization'] == 'Bearer test_meta_token_12345'
        assert call_kwargs['json']['to'] == '919876533001'
        assert call_kwargs['json']['text']['body'] == 'Test Message'

    @patch('notifications.providers.cloud_api_provider.requests.post')
    def test_cloud_api_provider_error_handling(self, mock_post, settings):
        """Tests CloudAPI provider diagnostics when Meta API returns an error."""
        settings.WHATSAPP_API_TOKEN = 'test_token'
        settings.WHATSAPP_PHONE_NUMBER_ID = '123'

        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            'error': {'message': 'Invalid template name', 'code': 100}
        }
        mock_post.return_value = mock_resp

        provider = CloudAPIWhatsAppProvider()
        success, wamid, err = provider.send_message("+919876533001", "Text")
        assert success is False
        assert wamid is None
        assert "Invalid template name" in err


@pytest.mark.django_db
class TestMessageTemplateFormatters:
    def test_payment_receipt_template_rendering(self, optin_member, superadmin_user):
        assignment = optin_member.plan_assignments.first()
        payment = Payment.objects.create(
            member=optin_member,
            plan_assignment=assignment,
            amount=Decimal('2400.00'),
            payment_mode=PaymentMode.UPI,
            reference_number="UPI-TEST-999",
            collected_by=superadmin_user,
            status=PaymentStatus.COMPLETED
        )
        msg = render_payment_receipt_message(payment)
        assert payment.receipt_number in msg
        assert "₹2,400.00" in msg
        assert "UPI / QR Code" in msg
        assert "7039145304" in msg
        assert optin_member.name in msg

    def test_renewal_upcoming_template_rendering(self, optin_member):
        msg = render_renewal_upcoming_message(optin_member, days_remaining=7)
        assert optin_member.name in msg
        assert optin_member.membership_id in msg
        assert "7 days" in msg
        assert "Annual Membership 2026" in msg

    def test_otp_message_template_rendering(self, optin_member):
        msg = render_otp_message(optin_member, "987123")
        assert "987123" in msg
        assert "5 minutes" in msg
        assert "7039145304" in msg


@pytest.mark.django_db
class TestWhatsAppWebhook:
    def test_webhook_get_verification_challenge_success(self, client, settings):
        settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN = 'secret_webhook_verify_token_2026'
        url = reverse('notifications:webhook')
        resp = client.get(url, {
            'hub.mode': 'subscribe',
            'hub.verify_token': 'secret_webhook_verify_token_2026',
            'hub.challenge': 'CHALLENGE_ACCEPTED_12345'
        })
        assert resp.status_code == 200
        assert resp.content.decode() == 'CHALLENGE_ACCEPTED_12345'

    def test_webhook_get_verification_token_mismatch_forbidden(self, client, settings):
        settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN = 'correct_token'
        url = reverse('notifications:webhook')
        resp = client.get(url, {
            'hub.mode': 'subscribe',
            'hub.verify_token': 'wrong_token',
            'hub.challenge': 'CHALLENGE'
        })
        assert resp.status_code == 403

    def test_webhook_post_delivery_status_updates(self, client, optin_member):
        """Inbound webhook updates matching message log from SENT to DELIVERED and READ."""
        log = send_whatsapp_notification(
            member=optin_member,
            template_type=NotificationTemplate.PAYMENT_DUE
        )
        wamid = log.external_message_id

        # 1. Simulate Meta 'delivered' webhook
        delivered_payload = {
            'object': 'whatsapp_business_account',
            'entry': [{
                'id': 'WHATSAPP_BUSINESS_ACCOUNT_ID',
                'changes': [{
                    'value': {
                        'messaging_product': 'whatsapp',
                        'statuses': [{
                            'id': wamid,
                            'status': 'delivered',
                            'timestamp': '1776000000',
                            'recipient_id': '919876533001'
                        }]
                    },
                    'field': 'messages'
                }]
            }]
        }

        resp = client.post(
            reverse('notifications:webhook'),
            data=json.dumps(delivered_payload),
            content_type='application/json'
        )
        assert resp.status_code == 200
        assert resp.json()['updated_records'] == 1

        log.refresh_from_db()
        assert log.status == NotificationStatus.DELIVERED
        assert log.delivered_at is not None

        # 2. Simulate Meta 'read' webhook
        read_payload = {
            'object': 'whatsapp_business_account',
            'entry': [{
                'id': 'WHATSAPP_BUSINESS_ACCOUNT_ID',
                'changes': [{
                    'value': {
                        'messaging_product': 'whatsapp',
                        'statuses': [{
                            'id': wamid,
                            'status': 'read',
                            'timestamp': '1776000100',
                            'recipient_id': '919876533001'
                        }]
                    },
                    'field': 'messages'
                }]
            }]
        }

        resp2 = client.post(
            reverse('notifications:webhook'),
            data=json.dumps(read_payload),
            content_type='application/json'
        )
        assert resp2.status_code == 200

        log.refresh_from_db()
        assert log.status == NotificationStatus.READ
        assert log.read_at is not None


@pytest.mark.django_db
class TestPaymentAutoWhatsAppReceipt:
    def test_recording_payment_triggers_whatsapp_receipt(self, client, superadmin_user, optin_member):
        """Recording a payment via staff flow dispatches WhatsApp receipt automatically."""
        client.force_login(superadmin_user)
        session = client.session
        session['user_id'] = superadmin_user.id
        session['otp_verified'] = True
        session.save()

        url = reverse('payments:payment_record', args=[optin_member.id])
        resp = client.post(url, {
            'amount': '2400.00',
            'payment_date': '2026-01-01',
            'payment_mode': PaymentMode.UPI,
            'reference_number': 'AUTO-WA-12345',
            'notes': 'Test auto WhatsApp'
        })
        assert resp.status_code in [302, 303]

        # Verify WhatsAppMessageLog was created
        log = WhatsAppMessageLog.objects.filter(
            member=optin_member,
            template_type=NotificationTemplate.PAYMENT_RECEIPT
        ).first()

        assert log is not None
        assert log.status == NotificationStatus.SENT
        assert "₹2,400.00" in log.message_body


@pytest.mark.django_db
class TestWhatsAppViewsAndPermissions:
    def _login_as(self, client, user):
        client.force_login(user)
        session = client.session
        session['user_id'] = user.id
        session['otp_verified'] = True
        session.save()

    def test_log_list_view_and_filtering(self, client, viewer_user, optin_member):
        send_whatsapp_notification(member=optin_member, template_type=NotificationTemplate.PAYMENT_DUE)
        self._login_as(client, viewer_user)

        resp = client.get(reverse('notifications:log_list'))
        assert resp.status_code == 200
        assert optin_member.name in resp.content.decode()

    def test_accountant_can_send_manual_whatsapp_message(self, client, accountant_user, optin_member):
        self._login_as(client, accountant_user)
        url = reverse('notifications:send_manual', args=[optin_member.id])

        resp = client.post(url, {
            'template_type': NotificationTemplate.PAYMENT_DUE,
            'custom_message': 'Custom reminder from accountant'
        })
        assert resp.status_code in [302, 303]

        log = WhatsAppMessageLog.objects.latest('created_at')
        assert log.member == optin_member
        assert log.message_body == 'Custom reminder from accountant'

    def test_viewer_denied_from_sending_manual_message(self, client, viewer_user, optin_member):
        self._login_as(client, viewer_user)
        url = reverse('notifications:send_manual', args=[optin_member.id])

        resp = client.post(url, {
            'template_type': NotificationTemplate.CUSTOM,
            'custom_message': 'Unauthorized text'
        })
        assert resp.status_code == 403
