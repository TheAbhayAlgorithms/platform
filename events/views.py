from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db import models
from django.urls import reverse

from accounts.decorators import admin_login_required, event_management_required
from accounts.models import RoleChoices
from members.models import Member, MemberStatus
from portal.decorators import member_login_required
from events.models import (
    Event,
    EventRegistration,
    EventCategory,
    EventStatus,
    RegistrationStatus,
)
from events.forms import EventForm, StaffEventRegistrationForm
from events.services import (
    register_member_for_event,
    cancel_event_registration,
    toggle_event_check_in,
    get_event_headcount_stats,
    export_event_attendees_excel,
    export_event_attendees_csv,
)


@admin_login_required
def event_list(request):
    """
    Staff dashboard listing all festival celebrations and institute events.
    Supports filtering by status, category, and text search.
    """
    status_filter = request.GET.get('status', '').strip()
    category_filter = request.GET.get('category', '').strip()
    search_query = request.GET.get('q', '').strip()

    events_qs = Event.objects.all().order_by('-start_date_time')

    if status_filter:
        events_qs = events_qs.filter(status=status_filter)
    if category_filter:
        events_qs = events_qs.filter(category=category_filter)
    if search_query:
        events_qs = events_qs.filter(
            models.Q(title__icontains=search_query) |
            models.Q(venue__icontains=search_query) |
            models.Q(description__icontains=search_query)
        )

    all_events = Event.objects.all()
    counts = {
        'total': all_events.count(),
        'published': all_events.filter(status=EventStatus.PUBLISHED).count(),
        'completed': all_events.filter(status=EventStatus.COMPLETED).count(),
        'cancelled': all_events.filter(status=EventStatus.CANCELLED).count(),
    }

    paginator = Paginator(events_qs, 15)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    can_manage = False
    profile = getattr(request.user, 'profile', None)
    if profile and profile.can_manage_events:
        can_manage = True

    context = {
        'page_obj': page_obj,
        'counts': counts,
        'status_filter': status_filter,
        'category_filter': category_filter,
        'search_query': search_query,
        'status_choices': EventStatus.choices,
        'category_choices': EventCategory.choices,
        'can_manage': can_manage,
    }
    return render(request, 'events/event_list.html', context)


@event_management_required
def event_create(request):
    """Staff action to create and publish a new festival celebration or event."""
    if request.method == 'POST':
        form = EventForm(request.POST)
        if form.is_valid():
            event = form.save(commit=False)
            event.created_by = request.user
            event.save()
            messages.success(request, f"Event '{event.title}' created successfully!")
            return redirect('events:event_detail', event_id=event.id)
    else:
        form = EventForm()

    context = {
        'form': form,
        'is_edit': False,
    }
    return render(request, 'events/event_form.html', context)


@admin_login_required
def event_detail(request, event_id):
    """
    Detailed dashboard for a specific festival or event.
    Displays venue, dates, capacity KPI cards, and attendee registrations.
    """
    event = get_object_or_404(Event, pk=event_id)
    stats = get_event_headcount_stats(event)

    registrations = event.registrations.select_related('member', 'registered_by').order_by('-registered_at')

    # Filter registrations by check-in status
    checked_filter = request.GET.get('checked_in', '').strip()
    if checked_filter == 'yes':
        registrations = registrations.filter(checked_in=True)
    elif checked_filter == 'no':
        registrations = registrations.filter(checked_in=False)

    can_manage = False
    profile = getattr(request.user, 'profile', None)
    if profile and profile.can_manage_events:
        can_manage = True

    context = {
        'event': event,
        'stats': stats,
        'registrations': registrations,
        'checked_filter': checked_filter,
        'can_manage': can_manage,
    }
    return render(request, 'events/event_detail.html', context)


@event_management_required
def event_edit(request, event_id):
    """Staff action to edit an existing event configuration."""
    event = get_object_or_404(Event, pk=event_id)

    if request.method == 'POST':
        form = EventForm(request.POST, instance=event)
        if form.is_valid():
            form.save()
            messages.success(request, f"Event '{event.title}' updated successfully.")
            return redirect('events:event_detail', event_id=event.id)
    else:
        form = EventForm(instance=event)

    context = {
        'form': form,
        'event': event,
        'is_edit': True,
    }
    return render(request, 'events/event_form.html', context)


@event_management_required
@require_POST
def event_cancel(request, event_id):
    """Staff action to mark an event as cancelled."""
    event = get_object_or_404(Event, pk=event_id)
    event.status = EventStatus.CANCELLED
    event.save(update_fields=['status'])
    messages.warning(request, f"Event '{event.title}' has been cancelled.")
    return redirect('events:event_detail', event_id=event.id)


@event_management_required
def event_register_member(request, event_id):
    """
    Staff action to manually register/RSVP a member for an event.
    Allows searching for any active member and adding family and guests.
    """
    event = get_object_or_404(Event, pk=event_id)

    if not event.is_registration_open:
        messages.error(request, f"Registrations for '{event.title}' are currently closed.")
        return redirect('events:event_detail', event_id=event.id)

    search_query = request.GET.get('q', '').strip()
    members_found = []
    if search_query:
        members_found = Member.objects.active_records().search_query(search_query)[:15]

    if request.method == 'POST':
        form = StaffEventRegistrationForm(request.POST)
        if form.is_valid():
            member_id = form.cleaned_data['member_id']
            member = get_object_or_404(Member, pk=member_id, is_removed=False)

            try:
                reg = register_member_for_event(
                    event=event,
                    member=member,
                    num_family_members=form.cleaned_data['num_family_members'],
                    num_guests=form.cleaned_data['num_guests'],
                    notes=form.cleaned_data['notes'],
                    registered_by=request.user
                )
                messages.success(
                    request,
                    f"Successfully registered {member.name} ({reg.total_headcount} attendees) for '{event.title}'."
                )
                return redirect('events:event_detail', event_id=event.id)
            except ValidationError as e:
                messages.error(request, e.message if hasattr(e, 'message') else str(e))
    else:
        form = StaffEventRegistrationForm()

    context = {
        'event': event,
        'form': form,
        'search_query': search_query,
        'members_found': members_found,
    }
    return render(request, 'events/event_register_member.html', context)


@event_management_required
@require_POST
def event_check_in_toggle(request, registration_id):
    """Quick desk check-in action toggling member arrival verification."""
    registration = get_object_or_404(EventRegistration, pk=registration_id)
    new_state = toggle_event_check_in(registration)

    state_str = "Checked In" if new_state else "Check-in Undone"
    messages.info(request, f"{registration.member.name}: {state_str}.")
    return redirect('events:event_detail', event_id=registration.event.id)


@event_management_required
@require_POST
def event_cancel_registration(request, registration_id):
    """Staff action to cancel a member registration and release seats."""
    registration = get_object_or_404(EventRegistration, pk=registration_id)
    event_id = registration.event.id
    member_name = registration.member.name

    cancel_event_registration(registration, reason="Staff cancelled on request")
    messages.warning(request, f"Registration for {member_name} has been cancelled.")
    return redirect('events:event_detail', event_id=event_id)


@admin_login_required
def event_export_attendees(request, event_id):
    """Exports attendee roster to Excel or CSV format."""
    event = get_object_or_404(Event, pk=event_id)
    fmt = request.GET.get('format', 'excel').lower()

    filename_base = f"attendees_event_{event.id}_{timezone.now().strftime('%Y%m%d')}"

    if fmt == 'csv':
        csv_data = export_event_attendees_csv(event)
        response = HttpResponse(csv_data, content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename_base}.csv"'
        return response
    else:
        excel_bytes = export_event_attendees_excel(event)
        response = HttpResponse(
            excel_bytes,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename_base}.xlsx"'
        return response


# =========================================================================
# MEMBER SELF-SERVICE PORTAL FESTIVAL EVENTS VIEWS
# =========================================================================

@member_login_required
def portal_event_list(request):
    """
    Member Portal page showcasing upcoming festival celebrations,
    family events, and RSVP status for the authenticated railway employee.
    """
    member_id = request.session['member_id']
    member = get_object_or_404(Member, pk=member_id, is_removed=False)

    now = timezone.now()
    upcoming_events = Event.objects.filter(
        is_active=True,
        status__in=[EventStatus.PUBLISHED, EventStatus.ONGOING],
        end_date_time__gt=now
    ).order_by('start_date_time')

    # Gather current member's registrations map
    my_registrations = {
        reg.event_id: reg
        for reg in EventRegistration.objects.filter(
            member=member,
            status=RegistrationStatus.CONFIRMED
        )
    }

    events_data = []
    for evt in upcoming_events:
        user_reg = my_registrations.get(evt.id)
        events_data.append({
            'event': evt,
            'is_registered': user_reg is not None,
            'registration': user_reg,
            'is_open': evt.is_registration_open,
            'remaining_capacity': evt.remaining_capacity,
        })

    context = {
        'member': member,
        'events_data': events_data,
    }
    return render(request, 'portal/events.html', context)


@member_login_required
@require_POST
def portal_event_rsvp(request, event_id):
    """Member action to RSVP for themselves and family directly from portal."""
    member_id = request.session['member_id']
    member = get_object_or_404(Member, pk=member_id, is_removed=False)
    event = get_object_or_404(Event, pk=event_id)

    try:
        num_family = int(request.POST.get('num_family_members', 0))
        num_guests = int(request.POST.get('num_guests', 0))
        notes = request.POST.get('notes', '').strip()

        reg = register_member_for_event(
            event=event,
            member=member,
            num_family_members=num_family,
            num_guests=num_guests,
            notes=notes,
            registered_by=None
        )
        messages.success(
            request,
            f"Your RSVP for '{event.title}' is confirmed! Total attendees: {reg.total_headcount}."
        )
    except (ValueError, ValidationError) as e:
        messages.error(request, e.message if hasattr(e, 'message') else str(e))

    return redirect('events:portal_events')


@member_login_required
@require_POST
def portal_event_cancel_rsvp(request, registration_id):
    """Member action to cancel their RSVP from portal."""
    member_id = request.session['member_id']
    member = get_object_or_404(Member, pk=member_id, is_removed=False)
    registration = get_object_or_404(
        EventRegistration,
        pk=registration_id,
        member=member,
        status=RegistrationStatus.CONFIRMED
    )

    cancel_event_registration(registration, reason="Member cancelled via portal")
    messages.info(request, f"Your RSVP for '{registration.event.title}' has been cancelled.")
    return redirect('events:portal_events')
