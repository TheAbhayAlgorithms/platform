import pytest
from datetime import date, timedelta
from decimal import Decimal
from django.utils import timezone
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User

from accounts.models import UserProfile, RoleChoices
from members.models import Member, MemberStatus, DepartmentChoices
from plans.models import Plan, MemberPlanAssignment
from payments.models import Payment, PaymentMode, PaymentStatus
from bookings.models import Facility, HallBooking, BookingStatus, PaymentStatus as BookingPaymentStatus
from transfers.models import Branch, InterDivisionalTransfer, TransferStatus, TransferType
from transfers.services import (
    check_member_clearance,
    create_transfer_request,
    approve_transfer_request,
    complete_transfer_request,
    reject_transfer_request,
    cancel_transfer_request
)


@pytest.fixture
def super_admin_user(db):
    user = User.objects.create_user(username='admin_test', email='admin_test@railclub.in', password='password123')
    UserProfile.objects.create(user=user, role=RoleChoices.SUPER_ADMIN, phone='+919876543210')
    return user


@pytest.fixture
def accountant_user(db):
    user = User.objects.create_user(username='acct_test', email='acct_test@railclub.in', password='password123')
    UserProfile.objects.create(user=user, role=RoleChoices.ACCOUNTANT, phone='+919876543211')
    return user


@pytest.fixture
def event_manager_user(db):
    user = User.objects.create_user(username='event_test', email='event_test@railclub.in', password='password123')
    UserProfile.objects.create(user=user, role=RoleChoices.EVENT_MANAGER, phone='+919876543212')
    return user


@pytest.fixture
def viewer_user(db):
    user = User.objects.create_user(username='view_test', email='view_test@railclub.in', password='password123')
    UserProfile.objects.create(user=user, role=RoleChoices.VIEWER, phone='+919876543213')
    return user


@pytest.fixture
def branches(db):
    home = Branch.objects.create(
        name="Delhi Main Club",
        code="NR-DLI",
        zone="Northern Railway",
        division="Delhi",
        city="New Delhi",
        state="Delhi",
        is_home_branch=True,
        is_active=True
    )
    dest = Branch.objects.create(
        name="Mumbai Central Institute",
        code="WR-MMCT",
        zone="Western Railway",
        division="Mumbai",
        city="Mumbai",
        state="Maharashtra",
        is_home_branch=False,
        is_active=True
    )
    return home, dest


@pytest.fixture
def active_member(db):
    member = Member(
        name="Rajesh Sharma",
        phone="+919811122233",
        employee_id="PF-778899",
        department=DepartmentChoices.ENGINEERING,
        status=MemberStatus.ACTIVE
    )
    member.save()
    return member


@pytest.mark.django_db
def test_branch_model_and_home_branch_uniqueness(branches):
    home, dest = branches
    assert home.is_home_branch is True
    assert dest.is_home_branch is False
    assert str(home) == "Delhi Main Club [NR-DLI] (Home Branch)"

    # Attempt to create another home branch should trigger ValidationError
    duplicate_home = Branch(
        name="Another Home",
        code="NR-EXTRA",
        zone="Northern Railway",
        division="Delhi",
        city="Delhi",
        state="Delhi",
        is_home_branch=True
    )
    with pytest.raises(ValidationError):
        duplicate_home.clean()


@pytest.mark.django_db
def test_sequential_transfer_and_noc_ids(branches, active_member):
    home, dest = branches
    year = timezone.now().year

    id1 = InterDivisionalTransfer.generate_next_transfer_id(year)
    assert id1 == f"TRF-{year}-00001"

    noc1 = InterDivisionalTransfer.generate_next_noc_number(year)
    assert noc1 == f"NOC-{year}-00001"

    # Creating a transfer persists sequential ID
    trf = create_transfer_request(
        member=active_member,
        from_branch=home,
        to_branch=dest,
        transfer_type=TransferType.OUTGOING,
        transfer_order_number="NR/ORD/2026/01",
        transfer_order_date=date.today(),
        effective_date=date.today() + timedelta(days=10)
    )
    assert trf.transfer_id == f"TRF-{year}-00001"

    id2 = InterDivisionalTransfer.generate_next_transfer_id(year)
    assert id2 == f"TRF-{year}-00002"


@pytest.mark.django_db
def test_member_clearance_evaluation(branches, active_member):
    home, dest = branches

    # 1. Clean member
    clearance = check_member_clearance(active_member)
    assert clearance['is_cleared'] is True

    # 2. Member status is EXPIRED
    active_member.status = MemberStatus.EXPIRED
    active_member.save()
    clearance = check_member_clearance(active_member)
    assert clearance['is_cleared'] is False
    assert any("status is currently 'Expired'" in r for r in clearance['reasons'])
    active_member.status = MemberStatus.ACTIVE
    active_member.save()

    # 3. Unsettled Hall Booking
    facility = Facility.objects.create(
        name="Main Banquet Hall",
        rent_per_slot=Decimal('5000.00'),
        full_day_rent=Decimal('9000.00'),
        security_deposit=Decimal('2000.00'),
        flat_electricity_charge=Decimal('1000.00')
    )
    booking = HallBooking.objects.create(
        facility=facility,
        member=active_member,
        purpose="Family Wedding",
        booking_date=date.today() + timedelta(days=30),
        rent_amount=Decimal('5000.00'),
        deposit_amount=Decimal('2000.00'),
        electricity_charges=Decimal('1000.00'),
        total_amount=Decimal('8000.00'),
        status=BookingStatus.CONFIRMED,
        payment_status=BookingPaymentStatus.PENDING
    )
    clearance = check_member_clearance(active_member)
    assert clearance['is_cleared'] is False
    assert any("hall reservation" in r for r in clearance['reasons'])

    # Settle booking
    booking.payment_status = BookingPaymentStatus.FULLY_PAID
    booking.save()
    clearance = check_member_clearance(active_member)
    assert clearance['is_cleared'] is True


@pytest.mark.django_db
def test_transfer_lifecycle_approval_and_completion(super_admin_user, branches, active_member):
    home, dest = branches
    year = timezone.now().year

    # 1. Initiate transfer
    trf = create_transfer_request(
        member=active_member,
        from_branch=home,
        to_branch=dest,
        transfer_type=TransferType.OUTGOING,
        transfer_order_number="NR/EE/TRF/401",
        transfer_order_date=date.today(),
        effective_date=date.today() + timedelta(days=15),
        requested_by=super_admin_user,
        remarks="Routine rotational transfer to Mumbai"
    )
    assert trf.status == TransferStatus.PENDING
    assert trf.dues_cleared is True
    assert trf.noc_number is None

    # Duplicate pending check
    with pytest.raises(ValidationError):
        create_transfer_request(
            member=active_member,
            from_branch=home,
            to_branch=dest,
            transfer_type=TransferType.OUTGOING,
            transfer_order_number="NR/EE/TRF/402",
            transfer_order_date=date.today(),
            effective_date=date.today() + timedelta(days=15)
        )

    # 2. Approve transfer
    approved_trf = approve_transfer_request(
        transfer=trf,
        user=super_admin_user,
        admin_remarks="All accounts audited and found clear."
    )
    assert approved_trf.status == TransferStatus.APPROVED
    assert approved_trf.noc_number == f"NOC-{year}-00001"
    assert approved_trf.noc_issued_at is not None
    assert approved_trf.actioned_by == super_admin_user

    # 3. Complete transfer
    completed_trf = complete_transfer_request(
        transfer=approved_trf,
        user=super_admin_user
    )
    assert completed_trf.status == TransferStatus.COMPLETED
    active_member.refresh_from_db()
    assert "Inter-Divisional Transfer (Outgoing)" in active_member.notes
    assert "NR/EE/TRF/401" in active_member.notes


@pytest.mark.django_db
def test_transfer_approval_requires_override_when_dues_unsettled(super_admin_user, branches, active_member):
    home, dest = branches

    # Put member into DUE status
    active_member.status = MemberStatus.DUE
    active_member.save()

    trf = create_transfer_request(
        member=active_member,
        from_branch=home,
        to_branch=dest,
        transfer_type=TransferType.OUTGOING,
        transfer_order_number="NR/EE/TRF/999",
        transfer_order_date=date.today(),
        effective_date=date.today() + timedelta(days=5)
    )
    assert trf.dues_cleared is False

    # Approval without override must fail
    with pytest.raises(ValidationError):
        approve_transfer_request(trf, user=super_admin_user, force_override=False)

    # Approval WITH override must succeed
    approved_trf = approve_transfer_request(trf, user=super_admin_user, force_override=True)
    assert approved_trf.status == TransferStatus.APPROVED
    assert approved_trf.dues_cleared is True
    assert "administratively overridden" in approved_trf.dues_remarks


@pytest.mark.django_db
def test_transfer_rejection_flow(super_admin_user, branches, active_member):
    home, dest = branches
    trf = create_transfer_request(
        member=active_member,
        from_branch=home,
        to_branch=dest,
        transfer_type=TransferType.OUTGOING,
        transfer_order_number="NR/EE/TRF/REJ",
        transfer_order_date=date.today(),
        effective_date=date.today() + timedelta(days=5)
    )

    # Rejection without reason fails
    with pytest.raises(ValidationError):
        reject_transfer_request(trf, user=super_admin_user, rejection_reason="")

    rejected = reject_transfer_request(trf, user=super_admin_user, rejection_reason="Railway order cancelled by DRM.")
    assert rejected.status == TransferStatus.REJECTED
    assert rejected.rejection_reason == "Railway order cancelled by DRM."


@pytest.mark.django_db
def test_transfers_views_and_rbac(client, super_admin_user, accountant_user, event_manager_user, viewer_user, branches, active_member):
    home, dest = branches

    # Unauthenticated access redirects
    resp = client.get(reverse('transfers:list'))
    assert resp.status_code == 302
    assert '/login/' in resp.url

    # Staff access to list
    client.force_login(viewer_user)
    resp = client.get(reverse('transfers:list'))
    assert resp.status_code == 200

    # Create transfer order by Event Manager
    client.force_login(event_manager_user)
    post_data = {
        'member': active_member.id,
        'from_branch': home.id,
        'to_branch': dest.id,
        'transfer_type': TransferType.OUTGOING,
        'transfer_order_number': 'NR/HQ/TRF/777',
        'transfer_order_date': '2026-10-15',
        'effective_date': '2026-11-01',
        'remarks': 'Administrative transfer order'
    }
    resp = client.post(reverse('transfers:create'), post_data, follow=True)
    assert resp.status_code == 200
    trf = InterDivisionalTransfer.objects.get(transfer_order_number='NR/HQ/TRF/777')
    assert trf.status == TransferStatus.PENDING

    # Viewer or Event Manager cannot approve (PermissionDenied HTTP 403)
    resp = client.post(reverse('transfers:approve', kwargs={'transfer_id': trf.transfer_id}))
    assert resp.status_code == 403

    # Accountant can approve
    client.force_login(accountant_user)
    resp = client.post(reverse('transfers:approve', kwargs={'transfer_id': trf.transfer_id}), follow=True)
    assert resp.status_code == 200
    trf.refresh_from_db()
    assert trf.status == TransferStatus.APPROVED
    assert trf.noc_number is not None

    # Print / view NOC certificate
    noc_url = reverse('transfers:noc', kwargs={'transfer_id': trf.transfer_id})
    resp = client.get(noc_url)
    assert resp.status_code == 200
    assert "NO OBJECTION CERTIFICATE" in resp.content.decode()
    assert trf.noc_number in resp.content.decode()


@pytest.mark.django_db
def test_member_portal_noc_access_and_idor_protection(client, super_admin_user, branches, active_member):
    home, dest = branches

    # Create & approve transfer with NOC for active_member
    trf = create_transfer_request(
        member=active_member,
        from_branch=home,
        to_branch=dest,
        transfer_type=TransferType.OUTGOING,
        transfer_order_number="NR/PORTAL/101",
        transfer_order_date=date.today(),
        effective_date=date.today() + timedelta(days=10)
    )
    approve_transfer_request(trf, user=super_admin_user)
    trf.refresh_from_db()

    # Another member
    other_member = Member(
        name="Sunil Verma",
        phone="+919833344455",
        status=MemberStatus.ACTIVE
    )
    other_member.save()

    # Log in as active_member in portal session
    session = client.session
    session['member_authenticated'] = True
    session['member_id'] = active_member.id
    session.save()

    # Member can view their own NOC
    own_noc_url = reverse('portal:download_noc', kwargs={'transfer_id': trf.transfer_id})
    resp = client.get(own_noc_url)
    assert resp.status_code == 200
    assert trf.noc_number in resp.content.decode()
    assert active_member.name in resp.content.decode()

    # Switch session to other_member
    session['member_id'] = other_member.id
    session.save()

    # Attempting to access active_member's NOC must fail with 404 (IDOR guard)
    resp = client.get(own_noc_url)
    assert resp.status_code == 404
