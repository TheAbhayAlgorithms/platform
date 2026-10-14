from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.core.exceptions import ValidationError, PermissionDenied
from django.db.models import Q, Count
from django.utils import timezone
from accounts.decorators import admin_login_required, role_required, super_admin_required
from accounts.models import RoleChoices
from members.models import Member
from transfers.models import Branch, InterDivisionalTransfer, TransferStatus, TransferType
from transfers.forms import BranchForm, TransferRequestForm, TransferApprovalForm, TransferRejectionForm
from transfers.services import (
    create_transfer_request,
    approve_transfer_request,
    complete_transfer_request,
    reject_transfer_request,
    cancel_transfer_request,
    check_member_clearance
)


@admin_login_required
def transfer_list(request):
    """
    Main dashboard for tracking inter-divisional transfer requests and clearance workflows.
    """
    status_filter = request.GET.get('status', 'ALL').upper()
    search_query = request.GET.get('q', '').strip()

    qs = InterDivisionalTransfer.objects.select_related('member', 'from_branch', 'to_branch', 'actioned_by')

    if status_filter in TransferStatus.values:
        qs = qs.filter(status=status_filter)

    if search_query:
        qs = qs.filter(
            Q(transfer_id__icontains=search_query) |
            Q(member__name__icontains=search_query) |
            Q(member__membership_id__icontains=search_query) |
            Q(transfer_order_number__icontains=search_query) |
            Q(noc_number__icontains=search_query)
        )

    # Statistics
    stats = {
        'total': InterDivisionalTransfer.objects.count(),
        'pending': InterDivisionalTransfer.objects.filter(status=TransferStatus.PENDING).count(),
        'approved': InterDivisionalTransfer.objects.filter(status=TransferStatus.APPROVED).count(),
        'completed': InterDivisionalTransfer.objects.filter(status=TransferStatus.COMPLETED).count(),
        'rejected': InterDivisionalTransfer.objects.filter(status=TransferStatus.REJECTED).count(),
    }

    context = {
        'transfers': qs,
        'current_status': status_filter,
        'search_query': search_query,
        'stats': stats,
        'statuses': TransferStatus.choices,
    }
    return render(request, 'transfers/transfer_list.html', context)


@admin_login_required
def transfer_detail(request, transfer_id):
    """
    Detailed audit view of an inter-divisional transfer request with live clearance status.
    """
    transfer = get_object_or_404(
        InterDivisionalTransfer.objects.select_related(
            'member', 'from_branch', 'to_branch', 'requested_by', 'actioned_by'
        ),
        transfer_id=transfer_id
    )

    # Re-evaluate live dues status if still pending
    live_clearance = None
    if transfer.status == TransferStatus.PENDING:
        live_clearance = check_member_clearance(transfer.member)

    approval_form = TransferApprovalForm()
    rejection_form = TransferRejectionForm()

    user_role = getattr(request.user, 'profile', None)
    can_approve = user_role and (user_role.is_super_admin or user_role.role == RoleChoices.ACCOUNTANT)

    context = {
        'transfer': transfer,
        'live_clearance': live_clearance,
        'approval_form': approval_form,
        'rejection_form': rejection_form,
        'can_approve': can_approve,
    }
    return render(request, 'transfers/transfer_detail.html', context)


@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ACCOUNTANT, RoleChoices.EVENT_MANAGER])
def transfer_create(request):
    """
    Create a new inter-divisional transfer order request.
    """
    member_id = request.GET.get('member_id')
    initial = {}
    preselected_member = None

    if member_id:
        try:
            preselected_member = Member.objects.get(pk=member_id, is_removed=False)
            initial['member'] = preselected_member
        except Member.DoesNotExist:
            pass

    if request.method == 'POST':
        form = TransferRequestForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                transfer = create_transfer_request(
                    member=data['member'],
                    from_branch=data['from_branch'],
                    to_branch=data['to_branch'],
                    transfer_type=data['transfer_type'],
                    transfer_order_number=data['transfer_order_number'],
                    transfer_order_date=data['transfer_order_date'],
                    effective_date=data['effective_date'],
                    requested_by=request.user,
                    remarks=data.get('remarks', '')
                )
                messages.success(
                    request,
                    f"Transfer Request {transfer.transfer_id} successfully registered. "
                    f"Dues Status: {'Clear' if transfer.dues_cleared else 'Pending Dues'}."
                )
                return redirect('transfers:detail', transfer_id=transfer.transfer_id)
            except ValidationError as e:
                messages.error(request, str(e))
    else:
        form = TransferRequestForm(initial=initial)

    return render(request, 'transfers/transfer_form.html', {
        'form': form,
        'preselected_member': preselected_member,
    })


@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ACCOUNTANT])
def transfer_approve(request, transfer_id):
    """
    Approve transfer request and issue digital No Objection Certificate.
    """
    transfer = get_object_or_404(InterDivisionalTransfer, transfer_id=transfer_id)
    if request.method == 'POST':
        form = TransferApprovalForm(request.POST)
        if form.is_valid():
            admin_remarks = form.cleaned_data.get('admin_remarks', '')
            force_override = form.cleaned_data.get('force_override', False)
            try:
                approve_transfer_request(
                    transfer=transfer,
                    user=request.user,
                    admin_remarks=admin_remarks,
                    force_override=force_override
                )
                messages.success(
                    request,
                    f"Transfer {transfer.transfer_id} approved. No Objection Certificate {transfer.noc_number} generated."
                )
            except ValidationError as e:
                messages.error(request, str(e))
    return redirect('transfers:detail', transfer_id=transfer.transfer_id)


@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ACCOUNTANT])
def transfer_reject(request, transfer_id):
    """
    Decline an inter-divisional transfer request.
    """
    transfer = get_object_or_404(InterDivisionalTransfer, transfer_id=transfer_id)
    if request.method == 'POST':
        form = TransferRejectionForm(request.POST)
        if form.is_valid():
            rejection_reason = form.cleaned_data['rejection_reason']
            try:
                reject_transfer_request(
                    transfer=transfer,
                    user=request.user,
                    rejection_reason=rejection_reason
                )
                messages.warning(request, f"Transfer request {transfer.transfer_id} has been rejected.")
            except ValidationError as e:
                messages.error(request, str(e))
    return redirect('transfers:detail', transfer_id=transfer.transfer_id)


@role_required([RoleChoices.SUPER_ADMIN, RoleChoices.ACCOUNTANT])
def transfer_complete(request, transfer_id):
    """
    Mark an approved transfer as finalized and update member records.
    """
    transfer = get_object_or_404(InterDivisionalTransfer, transfer_id=transfer_id)
    if request.method == 'POST':
        try:
            complete_transfer_request(transfer=transfer, user=request.user)
            messages.success(request, f"Transfer {transfer.transfer_id} has been finalized.")
        except ValidationError as e:
            messages.error(request, str(e))
    return redirect('transfers:detail', transfer_id=transfer.transfer_id)


@admin_login_required
def transfer_noc_view(request, transfer_id):
    """
    Printable and downloadable No Objection Certificate (NOC).
    """
    transfer = get_object_or_404(
        InterDivisionalTransfer.objects.select_related('member', 'from_branch', 'to_branch', 'actioned_by'),
        transfer_id=transfer_id
    )

    if not transfer.noc_number:
        messages.error(request, "No Objection Certificate has not yet been issued for this transfer.")
        return redirect('transfers:detail', transfer_id=transfer.transfer_id)

    home_branch = Branch.objects.filter(is_home_branch=True).first()

    context = {
        'transfer': transfer,
        'home_branch': home_branch,
        'printed_at': timezone.now(),
    }
    return render(request, 'transfers/transfer_noc.html', context)


@admin_login_required
def branch_list(request):
    """
    Directory of all registered Railway Club Branches & Divisions.
    """
    branches = Branch.objects.all().order_by('-is_home_branch', 'name')
    can_manage = getattr(request.user, 'profile', None) and request.user.profile.is_super_admin

    if request.method == 'POST' and can_manage:
        form = BranchForm(request.POST)
        if form.is_valid():
            try:
                branch = form.save()
                messages.success(request, f"Branch '{branch.name}' [{branch.code}] saved successfully.")
                return redirect('transfers:branches')
            except ValidationError as e:
                messages.error(request, str(e))
    else:
        form = BranchForm()

    return render(request, 'transfers/branch_list.html', {
        'branches': branches,
        'form': form,
        'can_manage': can_manage,
    })
