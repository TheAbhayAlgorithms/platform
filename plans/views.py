from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone

from accounts.decorators import admin_login_required
from members.models import Member, MemberStatus
from plans.models import Plan, DiscountConcession, MemberPlanAssignment
from plans.forms import PlanForm, DiscountConcessionForm, MemberPlanAssignForm

@admin_login_required
def plan_list_view(request):
    """Lists all membership plans and concession categories."""
    plans = Plan.objects.all().order_by('-is_active', 'fee')
    discounts = DiscountConcession.objects.all().order_by('-is_active', 'name')

    return render(request, 'plans/plan_list.html', {
        'plans': plans,
        'discounts': discounts,
    })


@admin_login_required
def plan_create_view(request):
    """Creates a new membership plan."""
    if request.user.profile.is_viewer:
        raise PermissionDenied("Viewer role is not authorized to create membership plans.")

    if request.method == 'POST':
        form = PlanForm(request.POST)
        if form.is_valid():
            plan = form.save()
            messages.success(request, f"Plan '{plan.name}' created successfully.")
            return redirect('plans:plan_list')
    else:
        form = PlanForm()

    return render(request, 'plans/plan_form.html', {
        'form': form,
        'title': 'Create Membership Plan',
    })


@admin_login_required
def plan_edit_view(request, plan_id):
    """Edits an existing plan. Does not retroactively alter fees of past assignments."""
    if request.user.profile.is_viewer:
        raise PermissionDenied("Viewer role is not authorized to edit membership plans.")

    plan = get_object_or_404(Plan, id=plan_id)

    if request.method == 'POST':
        form = PlanForm(request.POST, instance=plan)
        if form.is_valid():
            plan = form.save()
            messages.success(request, f"Plan '{plan.name}' updated successfully.")
            return redirect('plans:plan_list')
    else:
        form = PlanForm(instance=plan)

    return render(request, 'plans/plan_form.html', {
        'form': form,
        'title': f"Edit Plan: {plan.name}",
        'plan': plan,
    })


@admin_login_required
def plan_toggle_active_view(request, plan_id):
    """Toggles active/deactivated status of a plan."""
    if request.user.profile.is_viewer:
        raise PermissionDenied("Viewer role is not authorized to toggle plan status.")

    plan = get_object_or_404(Plan, id=plan_id)
    if request.method == 'POST':
        plan.is_active = not plan.is_active
        plan.save(update_fields=['is_active', 'updated_at'])
        state = "activated" if plan.is_active else "deactivated"
        messages.success(request, f"Plan '{plan.name}' has been {state}.")

    return redirect('plans:plan_list')


@admin_login_required
def discount_create_view(request):
    """Creates a new concession / discount rule."""
    if request.user.profile.is_viewer:
        raise PermissionDenied("Viewer role cannot create discount categories.")

    if request.method == 'POST':
        form = DiscountConcessionForm(request.POST)
        if form.is_valid():
            disc = form.save()
            messages.success(request, f"Discount category '{disc.name}' created.")
            return redirect('plans:plan_list')
    else:
        form = DiscountConcessionForm()

    return render(request, 'plans/discount_form.html', {'form': form})


@admin_login_required
def discount_toggle_active_view(request, discount_id):
    """Toggles active/deactivated status of a concession category."""
    if request.user.profile.is_viewer:
        raise PermissionDenied("Viewer role cannot modify discounts.")

    discount = get_object_or_404(DiscountConcession, id=discount_id)
    if request.method == 'POST':
        discount.is_active = not discount.is_active
        discount.save(update_fields=['is_active'])
        state = "activated" if discount.is_active else "deactivated"
        messages.success(request, f"Discount '{discount.name}' has been {state}.")

    return redirect('plans:plan_list')


@admin_login_required
def member_assign_plan_view(request, member_id):
    """
    Assigns a membership plan to a member.
    Calculates start and end dates, applies discounts, snapshots fee,
    and records audit assignment.
    """
    if request.user.profile.is_viewer:
        raise PermissionDenied("Viewer role cannot assign membership plans.")

    member = get_object_or_404(Member, id=member_id)

    # Suggest next start date: if current plan exists, suggest next day after current end date
    current_assignment = member.plan_assignments.filter(is_current=True).first()
    if current_assignment and current_assignment.end_date >= timezone.now().date():
        suggested_start = current_assignment.end_date + timezone.timedelta(days=1)
    else:
        suggested_start = timezone.now().date()

    if request.method == 'POST':
        form = MemberPlanAssignForm(request.POST)
        if form.is_valid():
            assignment = form.save(commit=False)
            assignment.member = member
            assignment.assigned_by = request.user
            assignment.is_current = True
            assignment.save()

            messages.success(
                request,
                f"Assigned '{assignment.plan.name}' to {member.name}. "
                f"Valid: {assignment.start_date:%d-%m-%Y} to {assignment.end_date:%d-%m-%Y} (Payable: ₹{assignment.final_fee:,.2f})."
            )
            return redirect('members:member_detail', member_id=member.id)
    else:
        form = MemberPlanAssignForm(initial={'start_date': suggested_start})

    return render(request, 'plans/member_assign_plan.html', {
        'member': member,
        'form': form,
        'current_assignment': current_assignment,
    })
