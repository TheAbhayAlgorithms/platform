from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.db.models import Q

from accounts.decorators import admin_login_required, super_admin_required
from accounts.models import RoleChoices
from members.models import Member, MemberFamily, MemberStatus, DepartmentChoices
from members.forms import MemberForm, MemberFamilyForm, MemberRemoveForm, MemberBulkImportForm
from members.services import process_bulk_member_import

@admin_login_required
def member_list_view(request):
    """
    Searchable, filterable directory of members with pagination.
    Accessible to all authenticated staff (Viewer is read-only).
    """
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    dept_filter = request.GET.get('dept', '').strip()
    show_removed = request.GET.get('show_removed') == '1'

    # Super Admin can optionally view soft-deleted members; others see active only
    if show_removed and request.user.profile.is_super_admin:
        qs = Member.objects.all()
    else:
        qs = Member.objects.active_records()

    if search_query:
        qs = qs.search_query(search_query)

    if status_filter:
        qs = qs.filter(status=status_filter)

    if dept_filter:
        qs = qs.filter(department=dept_filter)

    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'members/member_list.html', {
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'dept_filter': dept_filter,
        'show_removed': show_removed,
        'status_choices': MemberStatus.choices,
        'dept_choices': DepartmentChoices.choices,
        'total_count': qs.count(),
    })


@admin_login_required
def member_detail_view(request, member_id):
    """Displays full member profile, contact details, notes, and family dependents."""
    member = get_object_or_404(Member, id=member_id)
    family_members = member.family_members.all()
    family_form = MemberFamilyForm()

    return render(request, 'members/member_detail.html', {
        'member': member,
        'family_members': family_members,
        'family_form': family_form,
    })


@admin_login_required
def member_create_view(request):
    """Adds a new member. Viewers are restricted from creating members."""
    if request.user.profile.is_viewer:
        raise PermissionDenied("Viewer role is not authorized to create new members.")

    if request.method == 'POST':
        form = MemberForm(request.POST)
        if form.is_valid():
            member = form.save()
            messages.success(request, f"Member '{member.name}' ({member.membership_id}) created successfully.")
            return redirect('members:member_detail', member_id=member.id)
    else:
        form = MemberForm()

    return render(request, 'members/member_form.html', {
        'form': form,
        'title': 'Add New Member',
    })


@admin_login_required
def member_edit_view(request, member_id):
    """Edits an existing member. Viewers are restricted from modifying records."""
    if request.user.profile.is_viewer:
        raise PermissionDenied("Viewer role is not authorized to edit member records.")

    member = get_object_or_404(Member, id=member_id)

    if request.method == 'POST':
        form = MemberForm(request.POST, instance=member)
        if form.is_valid():
            member = form.save()
            messages.success(request, f"Member '{member.name}' ({member.membership_id}) updated successfully.")
            return redirect('members:member_detail', member_id=member.id)
    else:
        # Prepopulate decrypted phone
        form = MemberForm(instance=member, initial={'phone': member.phone})

    return render(request, 'members/member_form.html', {
        'form': form,
        'title': f"Edit Member: {member.name} ({member.membership_id})",
        'member': member,
    })


@admin_login_required
def member_family_add_view(request, member_id):
    """Adds a dependent family member to the member profile."""
    if request.user.profile.is_viewer:
        raise PermissionDenied("Viewer role cannot add family dependents.")

    member = get_object_or_404(Member, id=member_id)
    if request.method == 'POST':
        form = MemberFamilyForm(request.POST)
        if form.is_valid():
            family = form.save(commit=False)
            family.member = member
            family.save()
            messages.success(request, f"Family member '{family.name}' ({family.get_relationship_display()}) added.")
        else:
            messages.error(request, "Error adding family member. Please verify the entered details.")

    return redirect('members:member_detail', member_id=member.id)


@admin_login_required
def member_family_delete_view(request, member_id, family_id):
    """Deletes a dependent family member."""
    if request.user.profile.is_viewer:
        raise PermissionDenied("Viewer role cannot delete family dependents.")

    member = get_object_or_404(Member, id=member_id)
    family = get_object_or_404(MemberFamily, id=family_id, member=member)

    if request.method == 'POST':
        family_name = family.name
        family.delete()
        messages.success(request, f"Family dependent '{family_name}' removed.")

    return redirect('members:member_detail', member_id=member.id)


@super_admin_required
def member_soft_delete_view(request, member_id):
    """
    Soft-deletes a member (marks as REMOVED, retains history).
    Strictly restricted to Super Admin role.
    """
    member = get_object_or_404(Member, id=member_id)

    if request.method == 'POST':
        form = MemberRemoveForm(request.POST)
        if form.is_valid():
            reason = form.cleaned_data['reason']
            member.soft_delete(user=request.user, reason=reason)
            messages.success(
                request,
                f"Member '{member.name}' ({member.membership_id}) has been removed (soft-deleted). History retained."
            )
            return redirect('members:member_list')
    else:
        form = MemberRemoveForm()

    return render(request, 'members/member_confirm_delete.html', {
        'member': member,
        'form': form,
    })


@super_admin_required
def member_restore_view(request, member_id):
    """Restores a soft-deleted member back to Active status."""
    member = get_object_or_404(Member, id=member_id)
    if request.method == 'POST':
        member.restore(status=MemberStatus.ACTIVE)
        messages.success(request, f"Member '{member.name}' ({member.membership_id}) has been restored to Active status.")
    return redirect('members:member_detail', member_id=member.id)


@admin_login_required
def member_bulk_import_view(request):
    """
    Bulk import members from CSV or Excel (.xlsx) with validation report,
    duplicate phone detection, and dry-run preview.
    """
    if request.user.profile.is_viewer:
        raise PermissionDenied("Viewer role cannot perform bulk imports.")

    report = None
    if request.method == 'POST':
        form = MemberBulkImportForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = form.cleaned_data['file']
            dry_run = form.cleaned_data['dry_run']

            report = process_bulk_member_import(uploaded_file, dry_run=dry_run)

            if not dry_run and report['created_count'] > 0:
                messages.success(
                    request,
                    f"Successfully imported {report['created_count']} member(s) into RailClub Connect."
                )
                return redirect('members:member_list')
    else:
        form = MemberBulkImportForm()

    return render(request, 'members/member_import.html', {
        'form': form,
        'report': report,
    })
