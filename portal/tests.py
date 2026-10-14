from datetime import date, timedelta
from decimal import Decimal
import pytest
from freezegun import freeze_time
from django.urls import reverse
from django.utils import timezone
from django.core.management import call_command

from members.models import Member, MemberStatus, DepartmentChoices, MemberFamily
from plans.models import Plan, MemberPlanAssignment
from payments.models import Payment, PaymentMode, PaymentStatus
from portal.models import MemberOTP
from portal.services import (
    request_portal_otp,
    verify_portal_otp,
    mask_phone_number,
    get_portal_dashboard_context,
)


@pytest.fixture
def test_plan(db):
    return Plan.objects.create(
        name="Annual Membership 2026",
        fee=Decimal('2400.00'),
        duration_months=12,
        grace_period_days=15,
        is_active=True
    )


@pytest.fixture
def member_a(db, test_plan):
    member = Member.objects.create(
        name="Sunil Kumar",
        phone="+919876511111",
        employee_id="ER99001",
        department=DepartmentChoices.ELECTRICAL,
        status=MemberStatus.ACTIVE
    )
    assignment = MemberPlanAssignment.objects.create(
        member=member,
        plan=test_plan,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        base_fee=test_plan.fee,
        is_current=True
    )
    Payment.objects.create(
        member=member,
        plan_assignment=assignment,
        amount=Decimal('2400.00'),
        payment_mode=PaymentMode.UPI,
        reference_number="UPI-TEST-11111",
        status=PaymentStatus.COMPLETED
    )
    MemberFamily.objects.create(
        member=member,
        name="Pooja Kumar",
        relationship="SPOUSE",
        date_of_birth=date(1992, 5, 10)
    )
    return member


@pytest.fixture
def member_b(db, test_plan):
    member = Member.objects.create(
        name="Amit Verma",
        phone="+919876522222",
        employee_id="ER99002",
        department=DepartmentChoices.MECHANICAL,
        status=MemberStatus.DUE
    )
    assignment = MemberPlanAssignment.objects.create(
        member=member,
        plan=test_plan,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        base_fee=test_plan.fee,
        is_current=True
    )
    Payment.objects.create(
        member=member,
        plan_assignment=assignment,
        amount=Decimal('1000.00'),
        payment_mode=PaymentMode.CASH,
        reference_number="CASH-TEST-22222",
        status=PaymentStatus.COMPLETED
    )
    return member


@pytest.mark.django_db
class TestMemberPortalPhoneLookupAndOTP:
    def test_phone_lookup_and_otp_generation(self, member_a):
        """Valid Indian mobile number generates a 6-digit OTP stored hashed at rest."""
        success, error, member, raw_otp = request_portal_otp("9876511111")
        assert success is True
        assert member == member_a
        assert len(raw_otp) == 6
        assert raw_otp.isdigit()

        # Check DB security: only SHA-256 hash is saved
        otp_record = MemberOTP.objects.filter(member=member_a).latest('created_at')
        assert otp_record.otp_hash == MemberOTP.hash_otp(raw_otp)
        assert otp_record.otp_hash != raw_otp  # Not plaintext!
        assert otp_record.is_used is False
        assert otp_record.attempts == 0

    def test_unregistered_phone_rejected(self):
        """Unregistered mobile number returns clear error."""
        success, error, member, raw_otp = request_portal_otp("9999900000")
        assert success is False
        assert member is None
        assert "not found" in error.lower()

    def test_soft_deleted_member_rejected(self, member_a):
        """Soft-deleted/removed member cannot request OTP."""
        member_a.is_removed = True
        member_a.status = MemberStatus.REMOVED
        member_a.save()

        success, error, member, raw_otp = request_portal_otp("9876511111")
        assert success is False
        assert member is None

    def test_otp_rate_limiting(self, member_a):
        """Rate limiter blocks excessive OTP requests in a 10-minute window."""
        for _ in range(4):
            request_portal_otp(member_a.phone)

        # 5th attempt within 10 minutes must be throttled
        success, error, _, _ = request_portal_otp(member_a.phone)
        assert success is False
        assert "too many" in error.lower()


@pytest.mark.django_db
class TestMemberPortalOTPVerification:
    def test_successful_otp_verification(self, member_a):
        _, _, _, raw_otp = request_portal_otp(member_a.phone)
        is_valid, msg = verify_portal_otp(member_a, raw_otp)
        assert is_valid is True
        assert "successful" in msg.lower()

        otp_record = MemberOTP.objects.filter(member=member_a).latest('created_at')
        assert otp_record.is_used is True

    def test_wrong_otp_rejected_with_attempt_counter(self, member_a):
        _, _, _, _ = request_portal_otp(member_a.phone)
        is_valid, msg = verify_portal_otp(member_a, "000000")
        assert is_valid is False
        assert "2 attempt" in msg

        otp_record = MemberOTP.objects.filter(member=member_a).latest('created_at')
        assert otp_record.attempts == 1
        assert otp_record.is_used is False

    def test_lockout_after_three_wrong_attempts(self, member_a):
        _, _, _, _ = request_portal_otp(member_a.phone)
        verify_portal_otp(member_a, "111111")
        verify_portal_otp(member_a, "222222")
        is_valid, msg = verify_portal_otp(member_a, "333333")

        assert is_valid is False
        assert "locked" in msg.lower() or "maximum" in msg.lower()

        # Even correct OTP now fails because attempts >= 3
        otp_record = MemberOTP.objects.filter(member=member_a).latest('created_at')
        assert otp_record.attempts >= 3

    def test_expired_otp_rejected(self, member_a):
        with freeze_time("2026-10-14 10:00:00"):
            _, _, _, raw_otp = request_portal_otp(member_a.phone)

        # 6 minutes later -> expired
        with freeze_time("2026-10-14 10:06:00"):
            is_valid, msg = verify_portal_otp(member_a, raw_otp)
            assert is_valid is False
            assert "expired" in msg.lower()

    def test_reused_otp_rejected(self, member_a):
        _, _, _, raw_otp = request_portal_otp(member_a.phone)
        is_valid, _ = verify_portal_otp(member_a, raw_otp)
        assert is_valid is True

        # Second attempt with same OTP must be rejected
        is_valid_again, msg = verify_portal_otp(member_a, raw_otp)
        assert is_valid_again is False


@pytest.mark.django_db
class TestMemberPortalViewsAndAccessControl:
    def test_unauthenticated_dashboard_redirects_to_login(self, client):
        resp = client.get(reverse('portal:dashboard'))
        assert resp.status_code == 302
        assert reverse('portal:login') in resp.url

    def test_full_login_and_dashboard_flow(self, client, member_a):
        """End-to-end phone -> OTP -> dashboard view."""
        # 1. Submit phone number
        resp = client.post(reverse('portal:login'), {'phone': '9876511111'})
        assert resp.status_code == 302
        assert reverse('portal:verify_otp') in resp.url
        assert client.session['pending_member_id'] == member_a.id

        # 2. Get latest OTP from DB
        otp_record = MemberOTP.objects.filter(member=member_a, is_used=False).latest('created_at')
        # We need the plain code, or we can create an OTP directly
        raw_code = "654321"
        otp_record.otp_hash = MemberOTP.hash_otp(raw_code)
        otp_record.save()

        # 3. Submit OTP
        resp2 = client.post(reverse('portal:verify_otp'), {'otp': raw_code})
        assert resp2.status_code == 302
        assert reverse('portal:dashboard') in resp2.url
        assert client.session.get('member_authenticated') is True
        assert client.session.get('member_id') == member_a.id

        # 4. View dashboard
        resp3 = client.get(reverse('portal:dashboard'))
        assert resp3.status_code == 200
        content = resp3.content.decode()
        assert member_a.name in content
        assert member_a.membership_id in content
        assert "Pooja Kumar" in content  # Dependent displayed
        assert "Annual Membership 2026" in content

    def test_receipt_download_by_authorized_member(self, client, member_a):
        """Member can download their own payment receipt in PDF format."""
        session = client.session
        session['member_authenticated'] = True
        session['member_id'] = member_a.id
        session.save()

        payment = member_a.payments.first()
        url = reverse('portal:download_receipt', args=[payment.id])
        resp = client.get(url)

        assert resp.status_code == 200
        assert resp['Content-Type'] == 'application/pdf'
        assert f"Receipt_{payment.receipt_number}.pdf" in resp['Content-Disposition']
        assert resp.content.startswith(b'%PDF')

    def test_idor_protection_member_cannot_download_other_member_receipt(self, client, member_a, member_b):
        """IDOR Security: Member A cannot access Member B's receipt (returns 404)."""
        session = client.session
        session['member_authenticated'] = True
        session['member_id'] = member_a.id
        session.save()

        other_payment = member_b.payments.first()
        url = reverse('portal:download_receipt', args=[other_payment.id])
        resp = client.get(url)

        # Must return 404 Not Found (filtered by member=request.portal_member)
        assert resp.status_code == 404

    def test_member_logout(self, client, member_a):
        session = client.session
        session['member_authenticated'] = True
        session['member_id'] = member_a.id
        session.save()

        resp = client.get(reverse('portal:logout'))
        assert resp.status_code == 302
        assert reverse('portal:login') in resp.url
        assert client.session.get('member_authenticated') is None
        assert client.session.get('member_id') is None

        # Verify dashboard is no longer accessible
        resp2 = client.get(reverse('portal:dashboard'))
        assert resp2.status_code == 302
        assert reverse('portal:login') in resp2.url
