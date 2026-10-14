from datetime import date
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db import models

from accounts.decorators import admin_login_required, event_management_required
from members.models import Member, MemberStatus
from portal.decorators import member_login_required
from polls.models import (
    Poll,
    PollOption,
    PollVoter,
    Vote,
    PollType,
    PollStatus,
    MemberFeedback,
    FeedbackCategory,
    FeedbackStatus,
)
from polls.forms import (
    PollForm,
    PollOptionForm,
    FeedbackResponseForm,
    MemberFeedbackForm,
)
from polls.services import (
    cast_poll_vote,
    close_poll,
    submit_member_feedback,
    respond_to_feedback,
    export_poll_results_csv,
)


# =========================================================================
# STAFF POLL & ELECTION VIEWS
# =========================================================================

@admin_login_required
def poll_list(request):
    """
    Staff directory of all institute elections, AGM resolutions, and polls.
    """
    status_filter = request.GET.get('status', '').strip()
    type_filter = request.GET.get('type', '').strip()
    search_query = request.GET.get('q', '').strip()

    polls_qs = Poll.objects.all().order_by('-created_at')

    if status_filter:
        polls_qs = polls_qs.filter(status=status_filter)
    if type_filter:
        polls_qs = polls_qs.filter(poll_type=type_filter)
    if search_query:
        polls_qs = polls_qs.filter(
            models.Q(title__icontains=search_query) |
            models.Q(description__icontains=search_query)
        )

    all_polls = Poll.objects.all()
    counts = {
        'total': all_polls.count(),
        'open': all_polls.filter(status=PollStatus.OPEN).count(),
        'closed': all_polls.filter(status=PollStatus.CLOSED).count(),
        'draft': all_polls.filter(status=PollStatus.DRAFT).count(),
    }

    paginator = Paginator(polls_qs, 15)
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
        'type_filter': type_filter,
        'search_query': search_query,
        'status_choices': PollStatus.choices,
        'type_choices': PollType.choices,
        'can_manage': can_manage,
    }
    return render(request, 'polls/poll_list.html', context)


@event_management_required
def poll_create(request):
    """
    Staff action to set up a new election or poll.
    """
    if request.method == 'POST':
        form = PollForm(request.POST)
        if form.is_valid():
            poll = form.save(commit=False)
            poll.created_by = request.user
            poll.save()

            # Handle initial candidate options if submitted
            option_texts = request.POST.getlist('option_text')
            option_descs = request.POST.getlist('option_desc')
            order = 1
            for text, desc in zip(option_texts, option_descs):
                if text.strip():
                    PollOption.objects.create(
                        poll=poll,
                        text=text.strip(),
                        description=desc.strip(),
                        display_order=order
                    )
                    order += 1

            messages.success(request, f"Poll '{poll.title}' created successfully.")
            return redirect('polls:poll_detail', poll_id=poll.id)
    else:
        today = timezone.now().date()
        form = PollForm(initial={
            'start_date': today,
            'end_date': today + timezone.timedelta(days=14),
            'status': PollStatus.OPEN,
            'is_secret_ballot': True
        })

    context = {
        'form': form,
        'is_edit': False,
    }
    return render(request, 'polls/poll_form.html', context)


@admin_login_required
def poll_detail(request, poll_id):
    """
    Displays election/poll details, real-time vote distribution,
    participation turnout, leading option, and management controls.
    """
    poll = get_object_or_404(Poll.objects.prefetch_related('options', 'voters'), pk=poll_id)
    options = poll.options.all().order_by('-votes_count', 'display_order')

    can_manage = False
    profile = getattr(request.user, 'profile', None)
    if profile and profile.can_manage_events:
        can_manage = True

    option_form = PollOptionForm()

    context = {
        'poll': poll,
        'options': options,
        'can_manage': can_manage,
        'option_form': option_form,
        'total_members': Member.objects.active_records().count(),
    }
    return render(request, 'polls/poll_detail.html', context)


@event_management_required
def poll_edit(request, poll_id):
    """Staff action to modify poll parameters."""
    poll = get_object_or_404(Poll, pk=poll_id)

    if request.method == 'POST':
        form = PollForm(request.POST, instance=poll)
        if form.is_valid():
            form.save()
            messages.success(request, f"Poll '{poll.title}' updated successfully.")
            return redirect('polls:poll_detail', poll_id=poll.id)
    else:
        form = PollForm(instance=poll)

    context = {
        'form': form,
        'poll': poll,
        'is_edit': True,
    }
    return render(request, 'polls/poll_form.html', context)


@event_management_required
@require_POST
def poll_close(request, poll_id):
    """Staff action to close voting on an ongoing election."""
    poll = get_object_or_404(Poll, pk=poll_id)
    close_poll(poll, user=request.user)
    messages.info(request, f"Voting for '{poll.title}' has been closed.")
    return redirect('polls:poll_detail', poll_id=poll.id)


@event_management_required
@require_POST
def poll_option_add(request, poll_id):
    """Adds a new candidate or option to an existing poll."""
    poll = get_object_or_404(Poll, pk=poll_id)
    form = PollOptionForm(request.POST)
    if form.is_valid():
        opt = form.save(commit=False)
        opt.poll = poll
        opt.display_order = poll.options.count() + 1
        opt.save()
        messages.success(request, f"Option '{opt.text}' added.")
    else:
        messages.error(request, "Failed to add option.")
    return redirect('polls:poll_detail', poll_id=poll.id)


@admin_login_required
def poll_export_csv(request, poll_id):
    """Downloads a CSV summary of poll / election results."""
    poll = get_object_or_404(Poll, pk=poll_id)
    csv_data = export_poll_results_csv(poll)
    response = HttpResponse(csv_data, content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="poll_results_{poll.id}.csv"'
    return response


# =========================================================================
# STAFF FEEDBACK & GRIEVANCE VIEWS
# =========================================================================

@admin_login_required
def feedback_list(request):
    """
    Staff dashboard listing member feedback, grievances, and suggestions.
    """
    status_filter = request.GET.get('status', '').strip()
    category_filter = request.GET.get('category', '').strip()
    search_query = request.GET.get('q', '').strip()

    feedbacks_qs = MemberFeedback.objects.select_related('member', 'responded_by').order_by('-created_at')

    if status_filter:
        feedbacks_qs = feedbacks_qs.filter(status=status_filter)
    if category_filter:
        feedbacks_qs = feedbacks_qs.filter(category=category_filter)
    if search_query:
        feedbacks_qs = feedbacks_qs.filter(
            models.Q(subject__icontains=search_query) |
            models.Q(message__icontains=search_query) |
            models.Q(member__name__icontains=search_query)
        )

    all_fb = MemberFeedback.objects.all()
    counts = {
        'total': all_fb.count(),
        'submitted': all_fb.filter(status=FeedbackStatus.SUBMITTED).count(),
        'under_review': all_fb.filter(status=FeedbackStatus.UNDER_REVIEW).count(),
        'resolved': all_fb.filter(status=FeedbackStatus.RESOLVED).count(),
    }

    paginator = Paginator(feedbacks_qs, 15)
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
        'status_choices': FeedbackStatus.choices,
        'category_choices': FeedbackCategory.choices,
        'can_manage': can_manage,
    }
    return render(request, 'polls/feedback_list.html', context)


@admin_login_required
def feedback_detail(request, feedback_id):
    """
    Staff inspection of member feedback, allowing response submission and status update.
    """
    feedback = get_object_or_404(
        MemberFeedback.objects.select_related('member', 'responded_by'),
        pk=feedback_id
    )

    can_manage = False
    profile = getattr(request.user, 'profile', None)
    if profile and profile.can_manage_events:
        can_manage = True

    response_form = FeedbackResponseForm(instance=feedback)

    context = {
        'feedback': feedback,
        'can_manage': can_manage,
        'response_form': response_form,
    }
    return render(request, 'polls/feedback_detail.html', context)


@event_management_required
@require_POST
def feedback_respond(request, feedback_id):
    """Staff action to record official response on a grievance."""
    feedback = get_object_or_404(MemberFeedback, pk=feedback_id)
    form = FeedbackResponseForm(request.POST, instance=feedback)
    if form.is_valid():
        respond_to_feedback(
            feedback=feedback,
            admin_response=form.cleaned_data['admin_response'],
            new_status=form.cleaned_data['status'],
            is_public=form.cleaned_data['is_public'],
            user=request.user
        )
        messages.success(request, f"Response to feedback '{feedback.subject}' saved.")
    else:
        messages.error(request, "Failed to save response.")

    return redirect('polls:feedback_detail', feedback_id=feedback.id)


# =========================================================================
# MEMBER SELF-SERVICE PORTAL VIEWS
# =========================================================================

@member_login_required
def portal_polls_list(request):
    """
    Member portal view showing active elections & polls, indicating
    whether the member has already cast their ballot.
    """
    member_id = request.session['member_id']
    member = get_object_or_404(Member, pk=member_id, is_removed=False)

    polls = Poll.objects.filter(status__in=[PollStatus.OPEN, PollStatus.CLOSED]).prefetch_related('options').order_by('-start_date')

    # Get IDs of polls where this member has already voted
    voted_poll_ids = set(
        PollVoter.objects.filter(member=member).values_list('poll_id', flat=True)
    )

    context = {
        'member': member,
        'polls': polls,
        'voted_poll_ids': voted_poll_ids,
        'today': timezone.now().date(),
    }
    return render(request, 'portal/polls_list.html', context)


@member_login_required
@require_POST
def portal_poll_vote(request, poll_id):
    """
    Member casts a ballot in an active election or poll.
    """
    member_id = request.session['member_id']
    member = get_object_or_404(Member, pk=member_id, is_removed=False)
    poll = get_object_or_404(Poll, pk=poll_id)

    option_id = request.POST.get('option_id')
    if not option_id:
        messages.error(request, "Please select an option or candidate before submitting your vote.")
        return redirect('polls:portal_polls')

    option = get_object_or_404(PollOption, pk=option_id, poll=poll)

    try:
        cast_poll_vote(poll=poll, option=option, member=member)
        messages.success(request, f"Your vote in '{poll.title}' has been securely recorded! Thank you for participating.")
    except ValidationError as e:
        messages.error(request, e.message if hasattr(e, 'message') else str(e))

    return redirect('polls:portal_polls')


@member_login_required
def portal_feedback_view(request):
    """
    Member Portal page to submit feedback, view history of past suggestions,
    and see responses from Institute management.
    """
    member_id = request.session['member_id']
    member = get_object_or_404(Member, pk=member_id, is_removed=False)

    if request.method == 'POST':
        form = MemberFeedbackForm(request.POST)
        if form.is_valid():
            submit_member_feedback(
                member=member,
                category=form.cleaned_data['category'],
                subject=form.cleaned_data['subject'],
                message=form.cleaned_data['message'],
                rating=form.cleaned_data['rating']
            )
            messages.success(request, "Your feedback has been submitted to the Institute Office. Thank you!")
            return redirect('polls:portal_feedback')
        else:
            messages.error(request, "Please correct the errors in the feedback form.")
    else:
        form = MemberFeedbackForm()

    my_feedbacks = MemberFeedback.objects.filter(member=member).order_by('-created_at')
    public_feedbacks = MemberFeedback.objects.filter(is_public=True).select_related('member').order_by('-created_at')[:10]

    context = {
        'member': member,
        'form': form,
        'my_feedbacks': my_feedbacks,
        'public_feedbacks': public_feedbacks,
    }
    return render(request, 'portal/feedback.html', context)
