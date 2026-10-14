from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple
from django.db import transaction, models
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User

from members.models import Member, MemberStatus
from plans.models import Plan, DiscountConcession, MemberPlanAssignment
from payments.services import calculate_member_dues, sync_member_status_after_payment
from renewals.models import RenewalRecord


def calculate_renewal_dates(
    member: Member,
    target_plan: Plan,
    as_of_date: Optional[date] = None
) -> Dict[str, Any]:
    """
    Computes renewal validity dates based on member's current plan assignment.
    - If current assignment is still valid (end_date >= today):
      new validity starts on previous end_date + 1 day.
    - If current assignment has expired (end_date < today) or no plan:
      new validity starts today (as_of_date).
    """
    today = as_of_date or timezone.now().date()
    current_assignment = member.plan_assignments.filter(is_current=True).first()

    if current_assignment and current_assignment.end_date >= today:
        new_start_date = current_assignment.end_date + timedelta(days=1)
        is_early_renewal = True
    else:
        new_start_date = today
        is_early_renewal = False

    new_end_date = target_plan.compute_end_date(new_start_date)
    grace_end_date = new_end_date + timedelta(days=target_plan.grace_period_days)

    return {
        'current_assignment': current_assignment,
        'previous_end_date': current_assignment.end_date if current_assignment else None,
        'new_start_date': new_start_date,
        'new_end_date': new_end_date,
        'grace_end_date': grace_end_date,
        'is_early_renewal': is_early_renewal,
    }


def process_member_renewal(
    member: Member,
    renewed_by: Optional[User] = None,
    target_plan: Optional[Plan] = None,
    discount: Optional[DiscountConcession] = None,
    notes: str = "",
    as_of_date: Optional[date] = None
) -> Tuple[MemberPlanAssignment, RenewalRecord]:
    """
    Executes a member renewal transaction.
    Atomic with select_for_update to protect against concurrent/double clicks.
    
    1. Locks the member row.
    2. Identifies current assignment and checks idempotency / double-renewal.
    3. Calculates new validity dates (continuous if active, or starting today if expired).
    4. Creates new MemberPlanAssignment (auto-demotes previous to not current).
    5. Sets member status to DUE (or ACTIVE if ₹0 fee).
    6. Creates RenewalRecord audit log.
    """
    today = as_of_date or timezone.now().date()

    with transaction.atomic():
        # Lock member row for update to prevent concurrent double renewals
        locked_member = Member.objects.select_for_update().get(pk=member.pk)
        current_assignment = locked_member.plan_assignments.filter(is_current=True).first()

        # Determine target plan
        if target_plan is None:
            if current_assignment:
                target_plan = current_assignment.plan
            else:
                active_plan = Plan.objects.filter(is_active=True).first()
                if not active_plan:
                    raise ValidationError("No active membership plan available for renewal.")
                target_plan = active_plan

        if not target_plan.is_active:
            raise ValidationError(f"Plan '{target_plan.name}' is deactivated and cannot be used for renewal.")

        # Double-renewal guard:
        if current_assignment:
            if current_assignment.start_date > today:
                raise ValidationError(
                    f"Member already has a pending renewal cycle starting on "
                    f"{current_assignment.start_date:%d-%m-%Y}. Cannot renew again prematurely."
                )

            # Prevent repeated clicks if the current assignment was already created by a renewal
            has_existing_renewal = RenewalRecord.objects.filter(
                member=locked_member,
                new_assignment=current_assignment
            ).exists()
            if has_existing_renewal and (
                current_assignment.start_date >= today or
                current_assignment.end_date > today + timedelta(days=30)
            ):
                raise ValidationError(
                    f"Member has already been renewed for the cycle ending on "
                    f"{current_assignment.end_date:%d-%m-%Y}. Repeated renewal is blocked."
                )

        dates_info = calculate_renewal_dates(locked_member, target_plan, as_of_date=today)
        new_start_date = dates_info['new_start_date']
        new_end_date = dates_info['new_end_date']

        # Check if an assignment already exists for this exact validity start date
        if locked_member.plan_assignments.filter(start_date=new_start_date).exists():
            raise ValidationError(
                f"A plan assignment starting on {new_start_date:%d-%m-%Y} already exists for this member."
            )

        # Create new MemberPlanAssignment
        new_assignment = MemberPlanAssignment.objects.create(
            member=locked_member,
            plan=target_plan,
            discount=discount,
            start_date=new_start_date,
            end_date=new_end_date,
            grace_period_days=target_plan.grace_period_days,
            base_fee=target_plan.fee,
            is_current=True,
            assigned_by=renewed_by,
            notes=notes or f"Renewed on {today:%d-%m-%Y}"
        )

        # Create RenewalRecord audit entry
        renewal_record = RenewalRecord.objects.create(
            member=locked_member,
            previous_assignment=current_assignment,
            new_assignment=new_assignment,
            plan=target_plan,
            renewed_by=renewed_by,
            previous_end_date=current_assignment.end_date if current_assignment else None,
            new_start_date=new_start_date,
            new_end_date=new_end_date,
            fee_charged=new_assignment.final_fee,
            notes=notes
        )

        # Update member status
        if new_assignment.final_fee == Decimal('0.00'):
            locked_member.status = MemberStatus.ACTIVE
        else:
            locked_member.status = MemberStatus.DUE
        locked_member.save(update_fields=['status', 'updated_at'])

        return new_assignment, renewal_record


def process_auto_expiry(as_of_date: Optional[date] = None) -> Dict[str, Any]:
    """
    Automated batch sweep to transition expired members to EXPIRED status.
    Called by cron/management command or staff manual action.

    Rules:
    - Scans ACTIVE and DUE members who are not removed.
    - Evaluates their current plan assignment.
    - If current assignment end_date < as_of_date:
        - If as_of_date <= end_date + grace_period_days:
          Member is in grace period (not marked EXPIRED).
        - If as_of_date > end_date + grace_period_days:
          Member status is changed to EXPIRED.
    - If member has no plan assignment at all and is overdue, marked EXPIRED.
    """
    today = as_of_date or timezone.now().date()
    eligible_members = Member.objects.filter(
        is_removed=False,
        status__in=[MemberStatus.ACTIVE, MemberStatus.DUE]
    ).prefetch_related('plan_assignments')

    total_checked = 0
    expired_count = 0
    in_grace_count = 0
    active_valid_count = 0
    expired_member_ids = []

    with transaction.atomic():
        for member in eligible_members:
            total_checked += 1
            current_assignment = member.plan_assignments.filter(is_current=True).first()

            if not current_assignment:
                # No plan assignment found for this member
                member.status = MemberStatus.EXPIRED
                member.save(update_fields=['status', 'updated_at'])
                expired_count += 1
                expired_member_ids.append(member.membership_id)
                continue

            end_date = current_assignment.end_date
            grace_period_days = current_assignment.grace_period_days
            grace_end_date = end_date + timedelta(days=grace_period_days)

            if today <= end_date:
                # Within active validity period
                active_valid_count += 1
            elif end_date < today <= grace_end_date:
                # Inside grace period
                in_grace_count += 1
            else:
                # Grace period has lapsed -> Expire
                member.status = MemberStatus.EXPIRED
                member.save(update_fields=['status', 'updated_at'])
                expired_count += 1
                expired_member_ids.append(member.membership_id)

    return {
        'as_of_date': today,
        'total_checked': total_checked,
        'expired_count': expired_count,
        'in_grace_count': in_grace_count,
        'active_valid_count': active_valid_count,
        'expired_member_ids': expired_member_ids,
    }


def get_renewal_dashboard_data(
    filter_mode: str = 'all',
    search_query: str = '',
    department: str = '',
    as_of_date: Optional[date] = None
) -> Dict[str, Any]:
    """
    Fetches filtered member renewal records, counts, and financial breakdown
    for the Renewal Management Dashboard.
    """
    today = as_of_date or timezone.now().date()
    members_qs = Member.objects.active_records().prefetch_related(
        'plan_assignments__plan',
        'payments'
    )

    if department:
        members_qs = members_qs.filter(department=department)

    if search_query:
        members_qs = members_qs.search_query(search_query)

    # Process and categorize each member's renewal state
    all_items = []
    counts = {
        'overdue': 0,
        'within_7': 0,
        'within_15': 0,
        'within_30': 0,
        'in_grace': 0,
        'total_expiring_soon': 0,
        'total': 0,
    }

    for member in members_qs:
        current_assignment = member.plan_assignments.filter(is_current=True).first()
        if not current_assignment:
            continue

        end_date = current_assignment.end_date
        grace_days = current_assignment.grace_period_days
        grace_end_date = end_date + timedelta(days=grace_days)
        days_remaining = (end_date - today).days

        is_overdue = end_date < today
        is_in_grace = end_date < today <= grace_end_date
        is_within_7 = 0 <= days_remaining <= 7
        is_within_15 = 0 <= days_remaining <= 15
        is_within_30 = 0 <= days_remaining <= 30

        if is_overdue:
            counts['overdue'] += 1
        if is_in_grace:
            counts['in_grace'] += 1
        if is_within_7:
            counts['within_7'] += 1
        if is_within_15:
            counts['within_15'] += 1
        if is_within_30:
            counts['within_30'] += 1
        if 0 <= days_remaining <= 30:
            counts['total_expiring_soon'] += 1
        counts['total'] += 1

        # Check if item matches current filter
        include = False
        if filter_mode == 'all':
            include = True
        elif filter_mode == '7' and is_within_7:
            include = True
        elif filter_mode == '15' and is_within_15:
            include = True
        elif filter_mode == '30' and is_within_30:
            include = True
        elif filter_mode == 'overdue' and is_overdue:
            include = True
        elif filter_mode == 'grace' and is_in_grace:
            include = True

        if include:
            dues_info = calculate_member_dues(member)
            all_items.append({
                'member': member,
                'assignment': current_assignment,
                'plan': current_assignment.plan,
                'start_date': current_assignment.start_date,
                'end_date': end_date,
                'grace_end_date': grace_end_date,
                'days_remaining': days_remaining,
                'is_overdue': is_overdue,
                'is_in_grace': is_in_grace,
                'balance_due': dues_info['balance_due'],
                'is_fully_paid': dues_info['is_fully_paid'],
            })

    # Sort items: overdue first (most negative days), then upcoming soonest
    all_items.sort(key=lambda x: x['days_remaining'])

    return {
        'items': all_items,
        'counts': counts,
        'filter_mode': filter_mode,
        'today': today,
    }
