from datetime import timedelta
from decimal import Decimal
import pytest

from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from accounts.models import UserProfile, RoleChoices
from members.models import Member, MemberStatus, DepartmentChoices
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
from polls.forms import PollForm, PollOptionForm, FeedbackResponseForm, MemberFeedbackForm
from polls.services import (
    cast_poll_vote,
    create_poll_with_options,
    close_poll,
    submit_member_feedback,
    respond_to_feedback,
    export_poll_results_csv,
)


@pytest.fixture
def active_member(db):
    return Member.objects.create(
        name="Vikram Sharma",
        phone="+919876543210",
        employee_id="PF-1001",
        department=DepartmentChoices.OPERATING,
        status=MemberStatus.ACTIVE,
        whatsapp_opt_in=True
    )


@pytest.fixture
def second_member(db):
    return Member.objects.create(
        name="Deepa Rao",
        phone="+919876543212",
        employee_id="PF-1003",
        department=DepartmentChoices.ELECTRICAL,
        status=MemberStatus.ACTIVE,
        whatsapp_opt_in=True
    )


@pytest.fixture
def suspended_member(db):
    return Member.objects.create(
        name="Ramesh Yadav",
        phone="+919876543211",
        employee_id="PF-1002",
        department=DepartmentChoices.MECHANICAL,
        status=MemberStatus.SUSPENDED,
        whatsapp_opt_in=True
    )


@pytest.fixture
def admin_user(db):
    user = User.objects.create_user(username="admin_user", password="password123")
    UserProfile.objects.create(user=user, role=RoleChoices.SUPER_ADMIN)
    return user


@pytest.fixture
def event_manager_user(db):
    user = User.objects.create_user(username="event_mgr", password="password123")
    UserProfile.objects.create(user=user, role=RoleChoices.EVENT_MANAGER)
    return user


@pytest.fixture
def viewer_user(db):
    user = User.objects.create_user(username="viewer_user", password="password123")
    UserProfile.objects.create(user=user, role=RoleChoices.VIEWER)
    return user


@pytest.fixture
def open_election_poll(db, admin_user):
    today = timezone.now().date()
    poll = Poll.objects.create(
        title="Managing Committee General Representative 2026",
        poll_type=PollType.ELECTION,
        description="Vote for your division representative.",
        start_date=today - timedelta(days=1),
        end_date=today + timedelta(days=7),
        is_secret_ballot=True,
        status=PollStatus.OPEN,
        created_by=admin_user
    )
    PollOption.objects.create(poll=poll, text="Anand Kumar", description="Station Director", display_order=1)
    PollOption.objects.create(poll=poll, text="Suresh Verma", description="Chief Loco Inspector", display_order=2)
    PollOption.objects.create(poll=poll, text="Pooja Sen", description="Senior Section Engineer", display_order=3)
    return poll


# =========================================================================
# 1. MODEL & SERVICE UNIT TESTS
# =========================================================================

@pytest.mark.django_db
def test_poll_creation_and_clean_validation(admin_user):
    today = timezone.now().date()
    poll = Poll(
        title="Festival Budget Approval",
        poll_type=PollType.RESOLUTION,
        start_date=today,
        end_date=today - timedelta(days=1),
        created_by=admin_user
    )
    with pytest.raises(ValidationError):
        poll.clean()


@pytest.mark.django_db
def test_create_poll_with_options_service(admin_user):
    today = timezone.now().date()
    options_data = [
        {'text': 'Option A - Approve Full Budget', 'description': '100% allocation'},
        {'text': 'Option B - Revise Budget', 'description': 'Re-table at next AGM'}
    ]
    poll = create_poll_with_options(
        title="AGM Budget Resolution",
        poll_type=PollType.RESOLUTION,
        description="Resolution on Diwali celebration allocation.",
        start_date=today,
        end_date=today + timedelta(days=5),
        is_secret_ballot=False,
        status=PollStatus.OPEN,
        options_list=options_data,
        created_by=admin_user
    )

    assert poll.options.count() == 2
    assert poll.options.first().text == 'Option A - Approve Full Budget'


@pytest.mark.django_db
def test_create_poll_requires_minimum_two_options(admin_user):
    today = timezone.now().date()
    with pytest.raises(ValidationError, match="At least two"):
        create_poll_with_options(
            title="Single Option Fail",
            poll_type=PollType.OPINION_POLL,
            description="Testing",
            start_date=today,
            end_date=today + timedelta(days=5),
            is_secret_ballot=True,
            status=PollStatus.OPEN,
            options_list=[{'text': 'Only Choice'}],
            created_by=admin_user
        )


# =========================================================================
# 2. VOTING & ANONYMITY BUSINESS LOGIC TESTS
# =========================================================================

@pytest.mark.django_db
def test_cast_secret_ballot_vote(open_election_poll, active_member):
    opt = open_election_poll.options.first()
    vote = cast_poll_vote(poll=open_election_poll, option=opt, member=active_member)

    assert vote.poll == open_election_poll
    assert vote.option == opt
    # Secret ballot ensures member is NULL on the ballot!
    assert vote.member is None

    # But PollVoter audit registers that this member voted!
    assert PollVoter.objects.filter(poll=open_election_poll, member=active_member).exists()

    opt.refresh_from_db()
    assert opt.votes_count == 1
    assert open_election_poll.total_votes == 1
    assert opt.vote_percentage == 100.0


@pytest.mark.django_db
def test_cast_open_ballot_vote(admin_user, active_member):
    today = timezone.now().date()
    open_poll = Poll.objects.create(
        title="Open Survey Poll",
        poll_type=PollType.OPINION_POLL,
        start_date=today - timedelta(days=1),
        end_date=today + timedelta(days=5),
        is_secret_ballot=False,
        status=PollStatus.OPEN
    )
    opt = PollOption.objects.create(poll=open_poll, text="Choice 1")
    vote = cast_poll_vote(poll=open_poll, option=opt, member=active_member)

    assert vote.member == active_member


@pytest.mark.django_db
def test_strict_double_voting_prevention(open_election_poll, active_member):
    opt1 = open_election_poll.options.all()[0]
    opt2 = open_election_poll.options.all()[1]

    # First vote succeeds
    cast_poll_vote(poll=open_election_poll, option=opt1, member=active_member)

    # Second vote attempt by the same member MUST fail
    with pytest.raises(ValidationError, match="already voted"):
        cast_poll_vote(poll=open_election_poll, option=opt2, member=active_member)

    assert open_election_poll.total_votes == 1


@pytest.mark.django_db
def test_suspended_member_cannot_vote(open_election_poll, suspended_member):
    opt = open_election_poll.options.first()
    with pytest.raises(ValidationError, match="Only active"):
        cast_poll_vote(poll=open_election_poll, option=opt, member=suspended_member)


@pytest.mark.django_db
def test_voting_on_closed_or_expired_poll_rejected(active_member, admin_user):
    today = timezone.now().date()
    closed_poll = Poll.objects.create(
        title="Past Election",
        poll_type=PollType.ELECTION,
        start_date=today - timedelta(days=10),
        end_date=today - timedelta(days=1),
        status=PollStatus.CLOSED,
        created_by=admin_user
    )
    opt = PollOption.objects.create(poll=closed_poll, text="Candidate")

    with pytest.raises(ValidationError, match="Voting is currently closed"):
        cast_poll_vote(poll=closed_poll, option=opt, member=active_member)


# =========================================================================
# 3. MEMBER FEEDBACK & RESOLUTION TESTS
# =========================================================================

@pytest.mark.django_db
def test_submit_member_feedback(active_member):
    fb = submit_member_feedback(
        member=active_member,
        category=FeedbackCategory.SPORTS,
        subject="Badminton court lighting requires repair",
        message="Floodlight bulb #3 has been flickering for a week.",
        rating=3
    )

    assert fb.member == active_member
    assert fb.status == FeedbackStatus.SUBMITTED
    assert fb.rating == 3
    assert fb.is_public is False


@pytest.mark.django_db
def test_respond_to_feedback_lifecycle(active_member, event_manager_user):
    fb = submit_member_feedback(
        member=active_member,
        category=FeedbackCategory.CANTEEN,
        subject="Request for evening tea snacks variety",
        message="Please add poha or samosas to evening menu.",
        rating=4
    )

    updated = respond_to_feedback(
        feedback=fb,
        admin_response="Canteen vendor instructed to introduce fresh evening snacks from Monday.",
        new_status=FeedbackStatus.RESOLVED,
        is_public=True,
        user=event_manager_user
    )

    assert updated.status == FeedbackStatus.RESOLVED
    assert updated.is_public is True
    assert updated.responded_by == event_manager_user
    assert updated.responded_at is not None


# =========================================================================
# 4. EXPORT AND CSV GENERATION
# =========================================================================

@pytest.mark.django_db
def test_export_poll_results_csv(open_election_poll, active_member, second_member):
    opt1 = open_election_poll.options.all()[0]
    opt2 = open_election_poll.options.all()[1]

    cast_poll_vote(poll=open_election_poll, option=opt1, member=active_member)
    cast_poll_vote(poll=open_election_poll, option=opt2, member=second_member)

    csv_data = export_poll_results_csv(open_election_poll)
    assert open_election_poll.title in csv_data
    assert opt1.text in csv_data
    assert "Votes Received" in csv_data


# =========================================================================
# 5. STAFF VIEWS & RBAC PERMISSION TESTS
# =========================================================================

@pytest.mark.django_db
def test_staff_poll_list_access(open_election_poll, event_manager_user, viewer_user):
    client = Client()
    url = reverse('polls:poll_list')

    # Unauthenticated redirect
    assert client.get(url).status_code == 302

    # Event Manager allowed
    client.force_login(event_manager_user)
    resp = client.get(url)
    assert resp.status_code == 200
    assert "Committee Elections &amp; Member Polls" in resp.content.decode()

    # Viewer allowed read-only
    client.force_login(viewer_user)
    assert client.get(url).status_code == 200


@pytest.mark.django_db
def test_staff_poll_create_and_edit_rbac(open_election_poll, event_manager_user, viewer_user):
    client = Client()
    create_url = reverse('polls:poll_create')
    edit_url = reverse('polls:poll_edit', kwargs={'poll_id': open_election_poll.id})

    # Viewer forbidden (403)
    client.force_login(viewer_user)
    assert client.get(create_url).status_code == 403
    assert client.get(edit_url).status_code == 403

    # Event manager allowed
    client.force_login(event_manager_user)
    assert client.get(create_url).status_code == 200

    today = timezone.now().date()
    post_data = {
        'title': "Sports Committee Selection",
        'poll_type': PollType.ELECTION,
        'description': "Selection for Sports Secretary",
        'start_date': today.strftime('%Y-%m-%d'),
        'end_date': (today + timedelta(days=10)).strftime('%Y-%m-%d'),
        'is_secret_ballot': True,
        'status': PollStatus.OPEN,
        'option_text': ['Candidate 1', 'Candidate 2'],
        'option_desc': ['Badminton captain', 'Cricket captain'],
    }
    resp = client.post(create_url, post_data)
    assert resp.status_code == 302
    assert Poll.objects.filter(title="Sports Committee Selection").exists()


@pytest.mark.django_db
def test_staff_poll_close_and_option_add(open_election_poll, event_manager_user):
    client = Client()
    client.force_login(event_manager_user)

    # Add option
    opt_add_url = reverse('polls:poll_option_add', kwargs={'poll_id': open_election_poll.id})
    resp = client.post(opt_add_url, {'text': 'Write-in Candidate', 'description': 'New Nominee'})
    assert resp.status_code == 302
    assert open_election_poll.options.filter(text='Write-in Candidate').exists()

    # Close poll
    close_url = reverse('polls:poll_close', kwargs={'poll_id': open_election_poll.id})
    resp = client.post(close_url)
    assert resp.status_code == 302
    open_election_poll.refresh_from_db()
    assert open_election_poll.status == PollStatus.CLOSED


@pytest.mark.django_db
def test_staff_feedback_management_flow(active_member, event_manager_user, viewer_user):
    fb = submit_member_feedback(
        member=active_member,
        category=FeedbackCategory.MAINTENANCE,
        subject="Water cooler filter replacement",
        message="First floor corridor water cooler needs servicing.",
        rating=2
    )

    client = Client()

    # List
    client.force_login(viewer_user)
    assert client.get(reverse('polls:feedback_list')).status_code == 200

    # Detail
    assert client.get(reverse('polls:feedback_detail', kwargs={'feedback_id': fb.id})).status_code == 200

    # Respond - Viewer forbidden
    respond_url = reverse('polls:feedback_respond', kwargs={'feedback_id': fb.id})
    assert client.post(respond_url, {'admin_response': 'Denied', 'status': FeedbackStatus.RESOLVED}).status_code == 403

    # Respond - Event Manager allowed
    client.force_login(event_manager_user)
    resp = client.post(respond_url, {
        'admin_response': 'Work order issued to maintenance department. Filter replaced today.',
        'status': FeedbackStatus.RESOLVED,
        'is_public': True
    })
    assert resp.status_code == 302

    fb.refresh_from_db()
    assert fb.status == FeedbackStatus.RESOLVED
    assert fb.is_public is True


# =========================================================================
# 6. MEMBER SELF-SERVICE PORTAL TESTS
# =========================================================================

@pytest.mark.django_db
def test_portal_polls_list_and_voting(client, active_member, open_election_poll):
    session = client.session
    session['member_id'] = active_member.id
    session['member_authenticated'] = True
    session.save()

    # View list
    resp = client.get(reverse('polls:portal_polls'))
    assert resp.status_code == 200
    assert open_election_poll.title in resp.content.decode()

    # Submit vote
    vote_url = reverse('polls:portal_vote', kwargs={'poll_id': open_election_poll.id})
    opt = open_election_poll.options.first()
    resp = client.post(vote_url, {'option_id': opt.id})
    assert resp.status_code == 302

    # Verified recorded
    assert PollVoter.objects.filter(poll=open_election_poll, member=active_member).exists()

    # Re-submitting vote raises error message
    resp = client.post(vote_url, {'option_id': opt.id})
    assert resp.status_code == 302
    assert open_election_poll.total_votes == 1


@pytest.mark.django_db
def test_portal_feedback_submission(client, active_member):
    session = client.session
    session['member_id'] = active_member.id
    session['member_authenticated'] = True
    session.save()

    url = reverse('polls:portal_feedback')
    resp = client.get(url)
    assert resp.status_code == 200
    assert "Feedback &amp; Suggestions Box" in resp.content.decode()

    # Submit feedback POST
    post_data = {
        'category': FeedbackCategory.LIBRARY,
        'subject': "Request for Hindi railway journals",
        'message': "Please subscribe to monthly railway technical magazines in Hindi.",
        'rating': 5
    }
    resp = client.post(url, post_data)
    assert resp.status_code == 302

    fb = MemberFeedback.objects.get(subject="Request for Hindi railway journals")
    assert fb.member == active_member
    assert fb.category == FeedbackCategory.LIBRARY
    assert fb.rating == 5
