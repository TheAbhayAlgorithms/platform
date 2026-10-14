from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Any, Optional
from django.utils import timezone
from django.db import transaction

from members.models import Member, MemberStatus
from payments.services import calculate_member_dues
from notifications.models import (
    WhatsAppMessageLog,
    NotificationTemplate,
    NotificationStatus,
    ReminderMilestone,
    ScheduledReminderRecord,
)
from notifications.services import send_whatsapp_notification


def run_automated_whatsapp_reminders(
    as_of_date: Optional[date] = None,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Automated scheduled reminder batch runner:
    - Identifies members at upcoming renewal milestones (30d, 15d, 7d, 1d).
    - Identifies members in grace period or lapsed/expired.
    - Identifies members with outstanding payment dues (throttled to once per 14 days).
    - Respects DPDP opt-outs (member.whatsapp_opt_in=False).
    - Enforces de-duplication: no member is spammed twice for the same cycle milestone.
    """
    today = as_of_date or timezone.now().date()

    stats = {
        'as_of_date': today,
        'evaluated_members': 0,
        'renewal_reminders_sent': 0,
        'grace_reminders_sent': 0,
        'expired_reminders_sent': 0,
        'due_reminders_sent': 0,
        'skipped_optout': 0,
        'skipped_dedup': 0,
        'total_dispatched': 0,
        'dry_run': dry_run,
        'dispatched_logs': [],
    }

    eligible_members = Member.objects.active_records().prefetch_related(
        'plan_assignments__plan',
        'payments'
    )

    with transaction.atomic():
        for member in eligible_members:
            stats['evaluated_members'] += 1

            # DPDP Consent Check
            if not member.whatsapp_opt_in:
                stats['skipped_optout'] += 1
                continue

            current_assignment = member.plan_assignments.filter(is_current=True).first()
            if not current_assignment:
                continue

            end_date = current_assignment.end_date
            grace_days = current_assignment.grace_period_days
            grace_end_date = end_date + timedelta(days=grace_days)
            days_remaining = (end_date - today).days

            # 1. Renewal Milestones (30d, 15d, 7d, 1d)
            renewal_milestone = None
            if 25 <= days_remaining <= 30:
                renewal_milestone = ReminderMilestone.RENEWAL_30D
            elif 11 <= days_remaining <= 15:
                renewal_milestone = ReminderMilestone.RENEWAL_15D
            elif 5 <= days_remaining <= 7:
                renewal_milestone = ReminderMilestone.RENEWAL_7D
            elif 0 <= days_remaining <= 1:
                renewal_milestone = ReminderMilestone.RENEWAL_1D

            if renewal_milestone:
                already_sent = ScheduledReminderRecord.objects.filter(
                    plan_assignment=current_assignment,
                    milestone=renewal_milestone
                ).exists()

                if already_sent:
                    stats['skipped_dedup'] += 1
                else:
                    if not dry_run:
                        log = send_whatsapp_notification(
                            member=member,
                            template_type=NotificationTemplate.RENEWAL_UPCOMING,
                            days_remaining=max(1, days_remaining)
                        )
                        ScheduledReminderRecord.objects.create(
                            member=member,
                            plan_assignment=current_assignment,
                            milestone=renewal_milestone,
                            dispatched_date=today,
                            message_log=log
                        )
                        stats['dispatched_logs'].append(log.id)
                    stats['renewal_reminders_sent'] += 1
                    stats['total_dispatched'] += 1

            # 2. In Grace Period Notice
            if end_date < today <= grace_end_date:
                grace_milestone = ReminderMilestone.GRACE_PERIOD
                already_sent = ScheduledReminderRecord.objects.filter(
                    plan_assignment=current_assignment,
                    milestone=grace_milestone
                ).exists()

                if already_sent:
                    stats['skipped_dedup'] += 1
                else:
                    if not dry_run:
                        grace_msg = (
                            f"Namaste {member.name} ({member.membership_id}),\n\n"
                            f"Your Railway Institute membership ({current_assignment.plan.name}) expired on {end_date:%d-%m-%Y}. "
                            f"You are currently in the official {grace_days}-day grace period (valid until {grace_end_date:%d-%m-%Y}).\n\n"
                            f"Please renew your membership promptly to prevent suspension of your facility and festival privileges.\n\n"
                            f"Member Portal: https://railclub.local/portal/\n"
                            f"Support Helpline: 7039145304"
                        )
                        log = send_whatsapp_notification(
                            member=member,
                            template_type=NotificationTemplate.RENEWAL_UPCOMING,
                            custom_message=grace_msg
                        )
                        ScheduledReminderRecord.objects.create(
                            member=member,
                            plan_assignment=current_assignment,
                            milestone=grace_milestone,
                            dispatched_date=today,
                            message_log=log
                        )
                        stats['dispatched_logs'].append(log.id)
                    stats['grace_reminders_sent'] += 1
                    stats['total_dispatched'] += 1

            # 3. Lapsed / Expired Notice
            if today > grace_end_date and member.status == MemberStatus.EXPIRED:
                expired_milestone = ReminderMilestone.EXPIRED
                already_sent = ScheduledReminderRecord.objects.filter(
                    plan_assignment=current_assignment,
                    milestone=expired_milestone
                ).exists()

                if already_sent:
                    stats['skipped_dedup'] += 1
                else:
                    if not dry_run:
                        log = send_whatsapp_notification(
                            member=member,
                            template_type=NotificationTemplate.MEMBERSHIP_EXPIRED
                        )
                        ScheduledReminderRecord.objects.create(
                            member=member,
                            plan_assignment=current_assignment,
                            milestone=expired_milestone,
                            dispatched_date=today,
                            message_log=log
                        )
                        stats['dispatched_logs'].append(log.id)
                    stats['expired_reminders_sent'] += 1
                    stats['total_dispatched'] += 1

            # 4. Periodic Payment Due Notice (Only if DUE and not already notified in the last 14 days)
            if member.status == MemberStatus.DUE:
                dues_info = calculate_member_dues(member)
                if dues_info['balance_due'] > Decimal('0.00'):
                    due_milestone = ReminderMilestone.PAYMENT_DUE
                    recently_notified = ScheduledReminderRecord.objects.filter(
                        member=member,
                        milestone=due_milestone,
                        dispatched_date__gte=today - timedelta(days=14)
                    ).exists()

                    if recently_notified:
                        stats['skipped_dedup'] += 1
                    else:
                        if not dry_run:
                            log = send_whatsapp_notification(
                                member=member,
                                template_type=NotificationTemplate.PAYMENT_DUE
                            )
                            ScheduledReminderRecord.objects.create(
                                member=member,
                                plan_assignment=current_assignment,
                                milestone=due_milestone,
                                dispatched_date=today,
                                message_log=log
                            )
                            stats['dispatched_logs'].append(log.id)
                        stats['due_reminders_sent'] += 1
                        stats['total_dispatched'] += 1

    return stats
