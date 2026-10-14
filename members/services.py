import csv
import io
from datetime import datetime, date
from typing import Dict, Any, List, Tuple
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
import openpyxl

from members.models import Member, MemberStatus, DepartmentChoices
from core.encryption import normalize_phone, compute_blind_index

DEPARTMENT_MAP = {
    'engineering': DepartmentChoices.ENGINEERING,
    'civil engineering': DepartmentChoices.ENGINEERING,
    'operating': DepartmentChoices.OPERATING,
    'traffic': DepartmentChoices.OPERATING,
    'operating / traffic': DepartmentChoices.OPERATING,
    'commercial': DepartmentChoices.COMMERCIAL,
    'mechanical': DepartmentChoices.MECHANICAL,
    'mechanical engineering': DepartmentChoices.MECHANICAL,
    'electrical': DepartmentChoices.ELECTRICAL,
    'electrical engineering': DepartmentChoices.ELECTRICAL,
    'signal & telecom': DepartmentChoices.SIGNAL_TELECOM,
    's&t': DepartmentChoices.SIGNAL_TELECOM,
    'signal & telecommunication (s&t)': DepartmentChoices.SIGNAL_TELECOM,
    'personnel': DepartmentChoices.PERSONNEL,
    'personnel / administration': DepartmentChoices.PERSONNEL,
    'accounts': DepartmentChoices.ACCOUNTS,
    'accounts & finance': DepartmentChoices.ACCOUNTS,
    'medical': DepartmentChoices.MEDICAL,
    'security': DepartmentChoices.SECURITY_RPF,
    'rpf': DepartmentChoices.SECURITY_RPF,
    'railway protection force (rpf)': DepartmentChoices.SECURITY_RPF,
    'stores': DepartmentChoices.STORES,
    'stores / materials management': DepartmentChoices.STORES,
    'other': DepartmentChoices.OTHER,
}

STATUS_MAP = {
    'active': MemberStatus.ACTIVE,
    'due': MemberStatus.DUE,
    'expired': MemberStatus.EXPIRED,
    'suspended': MemberStatus.SUSPENDED,
}


def parse_import_file(uploaded_file) -> List[Dict[str, Any]]:
    """Reads rows from uploaded CSV or Excel file into a list of normalized dicts."""
    filename = uploaded_file.name.lower()
    raw_rows = []

    if filename.endswith('.csv'):
        content = uploaded_file.read().decode('utf-8-sig', errors='replace')
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            # Normalize dict keys (lowercase and stripped)
            normalized_row = {k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k}
            raw_rows.append(normalized_row)
    elif filename.endswith('.xlsx'):
        wb = openpyxl.load_workbook(uploaded_file, data_only=True)
        sheet = wb.active
        headers = []
        for cell in sheet[1]:
            val = str(cell.value).strip().lower() if cell.value is not None else ""
            headers.append(val)

        for row in sheet.iter_rows(min_row=2, values_only=True):
            if not any(row):
                continue
            row_dict = {}
            for idx, cell_val in enumerate(row):
                if idx < len(headers) and headers[idx]:
                    val = str(cell_val).strip() if cell_val is not None else ""
                    row_dict[headers[idx]] = val
            raw_rows.append(row_dict)

    return raw_rows


def process_bulk_member_import(uploaded_file, dry_run: bool = True) -> Dict[str, Any]:
    """
    Validates and processes bulk import from CSV/XLSX.
    Returns:
    {
        'total_rows': int,
        'valid_count': int,
        'error_count': int,
        'created_count': int,
        'errors': [{'row': int, 'name': str, 'phone': str, 'errors': list}],
        'preview': list of valid records,
    }
    """
    raw_rows = parse_import_file(uploaded_file)
    total_rows = len(raw_rows)
    row_errors = []
    valid_records = []
    seen_phones_in_batch = set()

    for row_num, row in enumerate(raw_rows, start=2):
        errors = []
        name = row.get('name') or row.get('member name') or row.get('full name') or ""
        phone = row.get('phone') or row.get('mobile') or row.get('contact') or ""
        emp_id = row.get('employee_id') or row.get('employee id') or row.get('pf number') or ""
        dept_str = (row.get('department') or 'other').lower()
        address = row.get('address') or ""
        status_str = (row.get('status') or 'active').lower()
        date_joined_str = row.get('date_joined') or row.get('date joined') or ""
        opt_in_str = str(row.get('whatsapp_opt_in', 'true')).strip().lower()

        if not name:
            errors.append("Member name is missing.")

        normalized_phone = ""
        if not phone:
            errors.append("Phone number is missing.")
        else:
            try:
                normalized_phone = normalize_phone(phone)
                # Check duplicate within this import file
                if normalized_phone in seen_phones_in_batch:
                    errors.append(f"Duplicate phone {normalized_phone} detected within this import file.")
                else:
                    seen_phones_in_batch.add(normalized_phone)

                # Check duplicate in database
                blind_idx = compute_blind_index(normalized_phone)
                if Member.objects.filter(phone_blind_index=blind_idx, is_removed=False).exists():
                    errors.append(f"Phone number {normalized_phone} is already registered to an existing member.")
            except ValidationError as e:
                errors.append(str(e))

        # Department parsing
        dept = DEPARTMENT_MAP.get(dept_str, DepartmentChoices.OTHER)
        # Status parsing
        status = STATUS_MAP.get(status_str, MemberStatus.ACTIVE)

        # Date joined parsing
        date_joined = timezone.now().date()
        if date_joined_str:
            for fmt in ['%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d']:
                try:
                    date_joined = datetime.strptime(date_joined_str, fmt).date()
                    break
                except ValueError:
                    continue

        opt_in = opt_in_str not in ['false', '0', 'no', 'off']

        if errors:
            row_errors.append({
                'row': row_num,
                'name': name or "[Unknown]",
                'phone': phone or "[Empty]",
                'errors': errors,
            })
        else:
            valid_records.append({
                'name': name,
                'phone': normalized_phone,
                'employee_id': emp_id,
                'department': dept,
                'address': address,
                'date_joined': date_joined,
                'status': status,
                'whatsapp_opt_in': opt_in,
            })

    created_count = 0
    if not dry_run and not row_errors:
        with transaction.atomic():
            for rec in valid_records:
                Member.objects.create(
                    name=rec['name'],
                    phone=rec['phone'],
                    employee_id=rec['employee_id'],
                    department=rec['department'],
                    address=rec['address'],
                    date_joined=rec['date_joined'],
                    status=rec['status'],
                    whatsapp_opt_in=rec['whatsapp_opt_in'],
                )
                created_count += 1

    return {
        'total_rows': total_rows,
        'valid_count': len(valid_records),
        'error_count': len(row_errors),
        'created_count': created_count,
        'errors': row_errors,
        'preview': valid_records[:10],  # First 10 for preview
        'dry_run': dry_run,
    }
