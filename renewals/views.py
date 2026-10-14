from datetime import date
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_POST
from django.urls import reverse
from django.utils import timezone

from accounts.models import RoleChoices
from accounts.decorators import admin_login_required, payment_management_required, role_required
from members.models import Member, DepartmentChoices
from plans.models import Plan, DiscountConcession, MemberPlanAssignment
from payments.services import calculate_member_dues
from renewals.models import RenewalRecord
from renewals.services import (
    get_renewal_dashboard_data,
    process_member_renewal,
    process_auto_expiry,
    calculate_renewal_dates,
)
from renewals.forms import MemberRenewalForm


@admin_login_required
def renewal_list(request):
    """
    Renewal Management Dashboard:
    - Lists upcoming expiries and overdue memberships.
    - Summary stat cards (overdue, 7 days, 15 days, 30 days, grace period).
    - Quick actions: One-click renewal, custom renewal, batch auto-expiry check.
    """
    filter_mode = request.GET.get('filter', 'all')
    search_query = request.GET.get('q', '').strip()
    department = request.GET.get('department', '').strip()

    data = get_renewal_dashboard_data(
        filter_mode=filter_mode,
        search_query=search_query,
        department=department,
    )

    paginator = Paginator(data['items'], 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    can_manage = False
    profile = getattr(request.user, 'profile', None)
    if profile and (profile.is_super_admin or profile.role == RoleChoices.ACCOUNTANT):
        can_manage = True

    context = {
        'page_obj': page_obj,
        'counts': data['counts'],
        'filter_mode': filter_mode,
        'search_query': search_query,
        'department': department,
        'department_choices': DepartmentChoices.choices,
        'today': data['today'],
        'can_manage': can_manage,
    }
    return render(request, 'renewals/renewal_list.html', context)


@payment_management_required
def renew_member(request, member_id):
    """
    Form view to renew a member's plan.
    Allows changing the plan or applying a discount.
    Shows prospective new validity dates.
    """
    member = get_object_or_404(Member, pk=member_id, is_removed=False)
    current_assignment = member.plan_assignments.filter(is_current=True).first()
    current_plan = current_assignment.plan if current_assignment else None

    # Determine default plan for prospective date calculation
    preview_plan = current_plan or Plan.objects.filter(is_active=True).first()
    preview_dates = None
    if preview_plan:
        preview_dates = calculate_renewal_dates(member, preview_plan)

    if request.method == 'POST':
        form = MemberRenewalForm(request.POST, current_plan=current_plan)
        if form.is_valid():
            selected_plan = form.cleaned_data['plan']
            selected_discount = form.cleaned_data['discount']
            notes = form.cleaned_data['notes']

            try:
                new_assignment, renewal_record = process_member_renewal(
                    member=member,
                    renewed_by=request.user,
                    target_plan=selected_plan,
                    discount=selected_discount,
                    notes=notes
                )
                messages.success(
                    request,
                    f"Successfully renewed {member.name} ({member.membership_id}) on {selected_plan.name}! "
                    f"New validity: {new_assignment.start_date:%d-%m-%Y} to {new_assignment.end_date:%d-%m-%Y}. "
                    f"Due amount: ₹{new_assignment.final_fee:,.2f}."
                )
                return redirect('renewals:member_history', member_id=member.pk)
            except ValidationError as e:
                error_msg = e.message if hasattr(e, 'message') else str(e)
                messages.error(request, f"Renewal failed: {error_msg}")
    else:
        form = MemberRenewalForm(current_plan=current_plan)

    context = {
        'member': member,
        'current_assignment': current_assignment,
        'current_plan': current_plan,
        'preview_dates': preview_dates,
        'form': form,
    }
    return render(request, 'renewals/renewal_form.html', context)


@payment_management_required
@require_POST
def one_click_renew(request, member_id):
    """
    One-click renewal action.
    Extends validity using the member's current active plan without discount.
    Prevents double renewal and sets status to DUE.
    """
    member = get_object_or_404(Member, pk=member_id, is_removed=False)
    current_assignment = member.plan_assignments.filter(is_current=True).first()

    if not current_assignment:
        messages.error(request, f"Member {member.name} does not have an existing plan. Please use standard renewal.")
        return redirect('renewals:renew_member', member_id=member.pk)

    try:
        new_assignment, renewal_record = process_member_renewal(
            member=member,
            renewed_by=request.user,
            target_plan=current_assignment.plan,
            discount=None,
            notes=f"One-click renewal executed by {request.user.username}"
        )
        messages.success(
            request,
            f"One-click renewal successful for {member.name}! "
            f"New period: {new_assignment.start_date:%d-%m-%Y} to {new_assignment.end_date:%d-%m-%Y}. "
            f"Amount due: ₹{new_assignment.final_fee:,.2f}."
        )
    except ValidationError as e:
        error_msg = e.message if hasattr(e, 'message') else str(e)
        messages.error(request, f"Cannot renew {member.name}: {error_msg}")

    # Return to previous page or renewal list
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('renewals:renewal_list')
    return redirect(next_url)


@admin_login_required
def member_renewal_history(request, member_id):
    """
    Detailed chronological timeline of plan assignments, renewals,
    validity periods, fees, and payments for a specific member.
    """
    member = get_object_or_404(Member, pk=member_id, is_removed=False)
    assignments = member.plan_assignments.all().order_by('-start_date')
    renewals = member.renewal_records.all().order_by('-renewal_date')
    dues_info = calculate_member_dues(member)

    can_manage = False
    profile = getattr(request.user, 'profile', None)
    if profile and (profile.is_super_admin or profile.role == RoleChoices.ACCOUNTANT):
        can_manage = True

    context = {
        'member': member,
        'assignments': assignments,
        'renewals': renewals,
        'dues_info': dues_info,
        'can_manage': can_manage,
        'today': timezone.now().date(),
    }
    return render(request, 'renewals/renewal_history.html', context)


@payment_management_required
@require_POST
def run_auto_expiry_sweep(request):
    """
    Manual trigger for automated expiry sweep.
    Transitions members whose end_date + grace period has lapsed to EXPIRED.
    """
    results = process_auto_expiry()
    msg = (
        f"Auto-expiry sweep completed as of {results['as_of_date']:%d-%m-%Y}. "
        f"Checked: {results['total_checked']} | "
        f"Expired: {results['expired_count']} | "
        f"In Grace Period: {results['in_grace_count']} | "
        f"Active/Valid: {results['active_valid_count']}."
    )
    if results['expired_count'] > 0:
        messages.warning(request, msg)
    else:
        messages.success(request, msg)

    return redirect('renewals:renewal_list')
