import io
import csv
from datetime import date
import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.db import connection
import openpyxl

from accounts.models import UserProfile, RoleChoices
from members.models import Member, MemberFamily, MemberStatus, DepartmentChoices
from core.encryption import compute_blind_index

@pytest.fixture
def superadmin_user(db):
    user = User.objects.create_user(
        username='superadmin_m2',
        password='TestPassword123!',
        is_staff=True,
        is_superuser=True,
    )
    UserProfile.objects.create(
        user=user,
        role=RoleChoices.SUPER_ADMIN,
        phone='+919876543210',
    )
    return user


@pytest.fixture
def accountant_user(db):
    user = User.objects.create_user(
        username='accountant_m2',
        password='TestPassword123!',
        is_staff=True,
    )
    UserProfile.objects.create(
        user=user,
        role=RoleChoices.ACCOUNTANT,
        phone='+919876543211',
    )
    return user


@pytest.fixture
def viewer_user(db):
    user = User.objects.create_user(
        username='viewer_m2',
        password='TestPassword123!',
        is_staff=True,
    )
    UserProfile.objects.create(
        user=user,
        role=RoleChoices.VIEWER,
        phone='+919876543213',
    )
    return user


@pytest.fixture
def sample_member(db):
    return Member.objects.create(
        name='Rajesh Pilot',
        phone='+919876599001',
        employee_id='WR-EMP-7701',
        department=DepartmentChoices.OPERATING,
        address='Railway Colony, Dadar',
        status=MemberStatus.ACTIVE,
        whatsapp_opt_in=True,
    )


@pytest.mark.django_db
class TestMemberModelAndEncryption:
    """Tests model validation, sequential ID generation, encryption, and blind index."""

    def test_auto_sequential_membership_id_generation(self):
        m1 = Member.objects.create(name='Member One', phone='9876599011')
        m2 = Member.objects.create(name='Member Two', phone='9876599012')
        assert m1.membership_id.startswith('RC-')
        assert m2.membership_id.startswith('RC-')
        # IDs must be distinct and sequential
        id1_num = int(m1.membership_id.split('-')[-1])
        id2_num = int(m2.membership_id.split('-')[-1])
        assert id2_num == id1_num + 1

    def test_phone_and_employee_id_encrypted_at_rest(self, sample_member):
        """Verifies raw database columns contain Fernet ciphertexts, not plain text."""
        with connection.cursor() as cursor:
            cursor.execute("SELECT phone, employee_id FROM members_member WHERE id = %s", [sample_member.id])
            row = cursor.fetchone()
            raw_phone, raw_emp_id = row[0], row[1]

            # Raw DB values must start with Fernet token prefix
            assert raw_phone.startswith('gAAAAA')
            assert raw_emp_id.startswith('gAAAAA')
            # Plaintext values must NOT exist in the raw column data
            assert '+919876599001' not in raw_phone
            assert 'WR-EMP-7701' not in raw_emp_id

        # Python model instance decrypts automatically
        sample_member.refresh_from_db()
        assert sample_member.phone == '+919876599001'
        assert sample_member.employee_id == 'WR-EMP-7701'

    def test_phone_format_validation_and_normalization(self):
        """Tests that phone numbers are normalized to +91XXXXXXXXXX or rejected."""
        m = Member.objects.create(name='Test Phone', phone='98765 44001')
        assert m.phone == '+919876544001'

        with pytest.raises(ValidationError):
            Member.objects.create(name='Bad Phone', phone='12345')

    def test_duplicate_phone_rejected_by_clean(self, sample_member):
        """Clean method rejects registering a phone already in use by an active member."""
        dup = Member(name='Duplicate Guy', phone='9876599001')
        with pytest.raises(ValidationError):
            dup.clean()


@pytest.mark.django_db
class TestMemberSearchAndFilter:
    """Tests search via keyed HMAC blind index and name queries."""

    def test_search_by_exact_phone_via_blind_index(self, sample_member):
        """Search by normalized phone or raw 10-digit phone hits blind index."""
        # Query using 10-digit raw phone
        results = Member.objects.search_query('9876599001')
        assert results.count() == 1
        assert results.first() == sample_member

        # Query using formatted +91 phone
        results2 = Member.objects.search_query('+919876599001')
        assert results2.count() == 1
        assert results2.first() == sample_member

    def test_search_by_employee_id_via_blind_index(self, sample_member):
        """Search by employee ID hits employee blind index."""
        results = Member.objects.search_query('WR-EMP-7701')
        assert results.count() == 1
        assert results.first() == sample_member

    def test_search_by_name_and_membership_id(self, sample_member):
        """Substring name search and membership ID exact match."""
        assert Member.objects.search_query('Rajesh').count() == 1
        assert Member.objects.search_query(sample_member.membership_id).count() == 1
        assert Member.objects.search_query('NonExistentPerson').count() == 0


@pytest.mark.django_db
class TestMemberViewsAndPermissions:
    """Tests CRUD views, role-based access control, and soft deletion."""

    def test_viewer_has_read_only_access(self, viewer_user, sample_member):
        client = Client()
        client.force_login(viewer_user)

        # Viewer can see directory and detail
        res_list = client.get(reverse('members:member_list'))
        assert res_list.status_code == 200
        res_detail = client.get(reverse('members:member_detail', kwargs={'member_id': sample_member.id}))
        assert res_detail.status_code == 200

        # Viewer is blocked (HTTP 403) from creating, editing, and deleting
        res_add = client.get(reverse('members:member_create'))
        assert res_add.status_code == 403

        res_edit = client.get(reverse('members:member_edit', kwargs={'member_id': sample_member.id}))
        assert res_edit.status_code == 403

        res_del = client.get(reverse('members:member_delete', kwargs={'member_id': sample_member.id}))
        assert res_del.status_code == 403

    def test_accountant_can_create_and_edit_but_cannot_delete(self, accountant_user, sample_member):
        client = Client()
        client.force_login(accountant_user)

        # Accountant can create
        post_data = {
            'name': 'Gopal Sharma',
            'phone': '9876588001',
            'employee_id': 'WR-ACC-1122',
            'department': DepartmentChoices.ACCOUNTS,
            'status': MemberStatus.ACTIVE,
            'date_joined': date.today().isoformat(),
            'whatsapp_opt_in': True,
        }
        res_create = client.post(reverse('members:member_create'), post_data)
        assert res_create.status_code == 302
        new_m = Member.objects.get(name='Gopal Sharma')
        assert new_m.phone == '+919876588001'

        # Accountant CANNOT delete (Super Admin only)
        res_del = client.get(reverse('members:member_delete', kwargs={'member_id': sample_member.id}))
        assert res_del.status_code == 403

    def test_super_admin_soft_delete_and_restore(self, superadmin_user, sample_member):
        client = Client()
        client.force_login(superadmin_user)

        # Soft delete with mandatory reason
        res_del = client.post(reverse('members:member_delete', kwargs={'member_id': sample_member.id}), {
            'reason': 'Voluntary resignation from railway service and club.',
        })
        assert res_del.status_code == 302
        assert res_del.url == reverse('members:member_list')

        sample_member.refresh_from_db()
        assert sample_member.is_removed is True
        assert sample_member.status == MemberStatus.REMOVED
        assert sample_member.removed_by == superadmin_user
        assert 'resignation' in sample_member.removal_reason

        # Active records queryset excludes soft-deleted member
        assert sample_member not in Member.objects.active_records()

        # Restore
        res_restore = client.post(reverse('members:member_restore', kwargs={'member_id': sample_member.id}))
        assert res_restore.status_code == 302
        sample_member.refresh_from_db()
        assert sample_member.is_removed is False
        assert sample_member.status == MemberStatus.ACTIVE
        assert sample_member in Member.objects.active_records()

    def test_family_dependent_add_and_delete(self, accountant_user, sample_member):
        client = Client()
        client.force_login(accountant_user)

        # Add family dependent
        res_add = client.post(reverse('members:member_family_add', kwargs={'member_id': sample_member.id}), {
            'name': 'Meena Pilot',
            'relationship': 'SPOUSE',
            'date_of_birth': '1986-05-15',
            'phone': '9876599002',
        })
        assert res_add.status_code == 302
        assert sample_member.family_members.count() == 1
        fam = sample_member.family_members.first()
        assert fam.name == 'Meena Pilot'

        # Delete family dependent
        res_del = client.post(
            reverse('members:member_family_delete', kwargs={'member_id': sample_member.id, 'family_id': fam.id})
        )
        assert res_del.status_code == 302
        assert sample_member.family_members.count() == 0


@pytest.mark.django_db
class TestBulkImport:
    """Tests bulk import via CSV and Excel, handling good, bad, and duplicate rows."""

    def test_bulk_import_csv_dry_run_and_live(self, superadmin_user):
        client = Client()
        client.force_login(superadmin_user)

        csv_content = """name,phone,employee_id,department,status
Sunil Gavaskar,9876511001,WR-OPS-501,Operating,active
Kapil Dev,9876511002,WR-ENG-502,Civil Engineering,active
"""
        csv_file = io.BytesIO(csv_content.encode('utf-8'))
        csv_file.name = 'members.csv'

        # Step 1: Dry Run (should validate without creating in DB)
        res_dry = client.post(reverse('members:member_import'), {
            'file': csv_file,
            'dry_run': 'on',
        })
        assert res_dry.status_code == 200
        assert Member.objects.filter(name='Sunil Gavaskar').count() == 0

        # Step 2: Live Run
        csv_file.seek(0)
        res_live = client.post(reverse('members:member_import'), {
            'file': csv_file,
            # dry_run not checked -> False
        })
        assert res_live.status_code == 302
        assert Member.objects.filter(name='Sunil Gavaskar').count() == 1
        assert Member.objects.filter(name='Kapil Dev').count() == 1

    def test_bulk_import_validates_errors_and_duplicates(self, superadmin_user, sample_member):
        client = Client()
        client.force_login(superadmin_user)

        # Row 1: Valid
        # Row 2: Bad phone format ('123')
        # Row 3: Duplicate phone against existing member ('9876599001')
        # Row 4: Duplicate phone within file (same as Row 1)
        csv_content = f"""name,phone,employee_id,department
Valid Member,9876512001,WR-OPS-601,Operating
Bad Phone Guy,12345,WR-OPS-602,Operating
Duplicate In DB,9876599001,WR-OPS-603,Operating
Duplicate In Batch,9876512001,WR-OPS-604,Operating
"""
        csv_file = io.BytesIO(csv_content.encode('utf-8'))
        csv_file.name = 'test_errors.csv'

        res = client.post(reverse('members:member_import'), {
            'file': csv_file,
            'dry_run': 'on',
        })
        assert res.status_code == 200
        content = res.content.decode()

        # Validation report must highlight all 3 problematic rows
        assert 'Row-by-Row Errors (3)' in content
        assert 'Invalid Indian mobile number' in content
        assert 'already registered to an existing member' in content
        assert 'Duplicate phone +919876512001 detected within this import file' in content

    def test_bulk_import_excel_xlsx(self, superadmin_user):
        """Tests Excel (.xlsx) file import via openpyxl."""
        client = Client()
        client.force_login(superadmin_user)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['name', 'phone', 'employee_id', 'department', 'status'])
        ws.append(['Rahul Dravid', '9876513001', 'CR-ENG-701', 'Civil Engineering', 'active'])
        ws.append(['VVS Laxman', '9876513002', 'CR-OPS-702', 'Operating', 'active'])

        xlsx_stream = io.BytesIO()
        wb.save(xlsx_stream)
        xlsx_stream.seek(0)
        xlsx_stream.name = 'members.xlsx'

        res = client.post(reverse('members:member_import'), {
            'file': xlsx_stream,
            # live import
        })
        assert res.status_code == 302
        assert Member.objects.filter(name='Rahul Dravid').count() == 1
        assert Member.objects.filter(name='VVS Laxman').count() == 1

