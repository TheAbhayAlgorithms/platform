import json
from django.db import models
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import RoleChoices
from accounts.decorators import admin_login_required, payment_management_required
from members.models import Member
from notifications.models import (
    WhatsAppMessageLog,
    NotificationTemplate,
    NotificationStatus,
    ReminderMilestone,
    ScheduledReminderRecord,
)
from notifications.services import (
    send_whatsapp_notification,
    process_whatsapp_webhook_payload,
)
from notifications.reminders import run_automated_whatsapp_reminders



@admin_login_required
def whatsapp_log_list(request):
    """
    Staff dashboard displaying chronological log of all outbound
    WhatsApp alerts, delivery statuses, and provider diagnostics.
    """
    status_filter = request.GET.get('status', '').strip()
    template_filter = request.GET.get('template', '').strip()
    search_query = request.GET.get('q', '').strip()

    logs_qs = WhatsAppMessageLog.objects.select_related('member').order_by('-created_at')

    if status_filter:
        logs_qs = logs_qs.filter(status=status_filter)
    if template_filter:
        logs_qs = logs_qs.filter(template_type=template_filter)
    if search_query:
        from core.encryption import compute_blind_index
        bindex = compute_blind_index(search_query.strip())
        logs_qs = logs_qs.filter(
            models.Q(member__name__icontains=search_query) |
            models.Q(member__membership_id__icontains=search_query) |
            models.Q(recipient_phone_blind_index=bindex) |
            models.Q(external_message_id__icontains=search_query)
        )

    # Calculate status counters
    all_logs = WhatsAppMessageLog.objects.all()
    counts = {
        'total': all_logs.count(),
        'sent': all_logs.filter(status=NotificationStatus.SENT).count(),
        'delivered': all_logs.filter(status=NotificationStatus.DELIVERED).count(),
        'read': all_logs.filter(status=NotificationStatus.READ).count(),
        'failed': all_logs.filter(status=NotificationStatus.FAILED).count(),
        'opted_out': all_logs.filter(status=NotificationStatus.OPTED_OUT).count(),
    }

    paginator = Paginator(logs_qs, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    can_manage = False
    profile = getattr(request.user, 'profile', None)
    if profile and (profile.is_super_admin or profile.role == RoleChoices.ACCOUNTANT):
        can_manage = True

    context = {
        'page_obj': page_obj,
        'counts': counts,
        'status_filter': status_filter,
        'template_filter': template_filter,
        'search_query': search_query,
        'status_choices': NotificationStatus.choices,
        'template_choices': NotificationTemplate.choices,
        'can_manage': can_manage,
        'sender_number': getattr(settings, 'WHATSAPP_SENDER_NUMBER', '7039145304'),
    }
    return render(request, 'notifications/log_list.html', context)


@payment_management_required
def whatsapp_send_manual(request, member_id):
    """
    Staff action view allowing authorized staff to manually compose
    and trigger a WhatsApp alert to a member.
    """
    member = get_object_or_404(Member, pk=member_id, is_removed=False)

    if request.method == 'POST':
        template_type = request.POST.get('template_type', NotificationTemplate.CUSTOM)
        custom_message = request.POST.get('custom_message', '').strip()

        log = send_whatsapp_notification(
            member=member,
            template_type=template_type,
            custom_message=custom_message or None
        )

        if log.status in [NotificationStatus.SENT, NotificationStatus.DELIVERED]:
            messages.success(
                request,
                f"WhatsApp alert successfully sent to {member.name} ({member.phone})."
            )
        elif log.status == NotificationStatus.OPTED_OUT:
            messages.warning(
                request,
                f"Notification not sent: {member.name} has opted out of WhatsApp automated alerts."
            )
        else:
            messages.error(
                request,
                f"WhatsApp delivery failed: {log.error_message}"
            )

        return redirect('notifications:log_list')

    context = {
        'member': member,
        'template_choices': NotificationTemplate.choices,
    }
    return render(request, 'notifications/send_manual.html', context)


@payment_management_required
@require_POST
def whatsapp_retry_message(request, log_id):
    """Retries sending a previously failed WhatsApp message."""
    log = get_object_or_404(WhatsAppMessageLog, pk=log_id)
    if not log.member:
        messages.error(request, "Cannot retry notification without associated member record.")
        return redirect('notifications:log_list')

    new_log = send_whatsapp_notification(
        member=log.member,
        template_type=log.template_type,
        custom_message=log.message_body
    )

    if new_log.status in [NotificationStatus.SENT, NotificationStatus.DELIVERED]:
        messages.success(request, f"Retry successful for {log.member.name}.")
    else:
        messages.error(request, f"Retry failed: {new_log.error_message}")

    return redirect('notifications:log_list')


@csrf_exempt
def whatsapp_webhook(request):
    """
    Meta WhatsApp Cloud API Webhook:
    - GET: Verification challenge handling
    - POST: Delivery report ingestion (sent, delivered, read, failed)
    """
    if request.method == 'GET':
        mode = request.GET.get('hub.mode')
        token = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge')

        expected_token = getattr(settings, 'WHATSAPP_WEBHOOK_VERIFY_TOKEN', '')

        if mode == 'subscribe' and token and token == expected_token:
            return HttpResponse(challenge, content_type='text/plain', status=200)
        return HttpResponseForbidden("Forbidden: Webhook verify token mismatch.")

    elif request.method == 'POST':
        try:
            payload = json.loads(request.body.decode('utf-8'))
            updated = process_whatsapp_webhook_payload(payload)
            return JsonResponse({'status': 'success', 'updated_records': updated}, status=200)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    return HttpResponseForbidden("Method not allowed.")


@admin_login_required
def whatsapp_reminders_dashboard(request):
    """
    Staff dashboard displaying status and logs of automated scheduled WhatsApp reminders:
    - 30d, 15d, 7d, 1d Renewal Notices
    - In-Grace Period Notices
    - Expired/Lapsed Notices
    - Periodic Balance Due Reminders
    """
    milestone_filter = request.GET.get('milestone', '').strip()

    records_qs = ScheduledReminderRecord.objects.select_related(
        'member',
        'plan_assignment__plan',
        'message_log'
    ).order_by('-dispatched_date', '-created_at')

    if milestone_filter:
        records_qs = records_qs.filter(milestone=milestone_filter)

    all_records = ScheduledReminderRecord.objects.all()
    counts = {
        'total': all_records.count(),
        'renewal_30d': all_records.filter(milestone=ReminderMilestone.RENEWAL_30D).count(),
        'renewal_15d': all_records.filter(milestone=ReminderMilestone.RENEWAL_15D).count(),
        'renewal_7d': all_records.filter(milestone=ReminderMilestone.RENEWAL_7D).count(),
        'renewal_1d': all_records.filter(milestone=ReminderMilestone.RENEWAL_1D).count(),
        'grace': all_records.filter(milestone=ReminderMilestone.GRACE_PERIOD).count(),
        'expired': all_records.filter(milestone=ReminderMilestone.EXPIRED).count(),
        'dues': all_records.filter(milestone=ReminderMilestone.PAYMENT_DUE).count(),
    }

    paginator = Paginator(records_qs, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    can_manage = False
    profile = getattr(request.user, 'profile', None)
    if profile and (profile.is_super_admin or profile.role == RoleChoices.ACCOUNTANT):
        can_manage = True

    context = {
        'page_obj': page_obj,
        'counts': counts,
        'milestone_filter': milestone_filter,
        'milestone_choices': ReminderMilestone.choices,
        'can_manage': can_manage,
        'today': timezone.now().date(),
    }
    return render(request, 'notifications/reminders_dashboard.html', context)


@payment_management_required
@require_POST
def trigger_reminders_sweep(request):
    """
    Manual trigger view for staff to execute the scheduled reminder engine immediately.
    """
    stats = run_automated_whatsapp_reminders(as_of_date=timezone.now().date(), dry_run=False)

    messages.success(
        request,
        f"Automated WhatsApp sweep completed: {stats['total_dispatched']} notices dispatched "
        f"({stats['renewal_reminders_sent']} renewals, {stats['grace_reminders_sent']} grace, "
        f"{stats['expired_reminders_sent']} expired, {stats['due_reminders_sent']} dues). "
        f"{stats['skipped_dedup']} skipped (already sent), {stats['skipped_optout']} skipped (DPDP opt-out)."
    )
    return redirect('notifications:reminders_dashboard')

