import csv
import io
from typing import List, Dict, Any, Optional
from django.db import transaction, models
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User

from members.models import Member, MemberStatus
from polls.models import (
    Poll,
    PollOption,
    PollVoter,
    Vote,
    PollStatus,
    MemberFeedback,
    FeedbackStatus,
)


def cast_poll_vote(
    poll: Poll,
    option: PollOption,
    member: Member,
    ip_address: Optional[str] = None
) -> Vote:
    """
    Validates eligibility, guards against double-voting, and casts a ballot.
    If poll.is_secret_ballot is True, member identity is decoupled from Vote.
    """
    if member.is_removed:
        raise ValidationError("Cannot cast vote: Member record is marked removed.")

    if member.status != MemberStatus.ACTIVE:
        raise ValidationError(
            f"Only active railway members may vote. Current status: {member.get_status_display()}."
        )

    today = timezone.now().date()
    if poll.status != PollStatus.OPEN:
        raise ValidationError("Voting is currently closed.")

    if today < poll.start_date:
        raise ValidationError(f"Voting opens on {poll.start_date:%d-%m-%Y}.")

    if today > poll.end_date:
        raise ValidationError(f"Voting closed on {poll.end_date:%d-%m-%Y}.")

    if option.poll_id != poll.id:
        raise ValidationError("The selected candidate or option does not belong to this poll.")

    with transaction.atomic():
        # Concurrency safety: check and lock if already voted
        already_voted = PollVoter.objects.filter(
            poll=poll,
            member=member
        ).exists()

        if already_voted:
            raise ValidationError("You have already voted in this election / poll. Duplicate votes are strictly barred.")

        # Record participation audit
        PollVoter.objects.create(
            poll=poll,
            member=member
        )

        # Record ballot choice
        ballot_member = None if poll.is_secret_ballot else member
        vote = Vote.objects.create(
            poll=poll,
            option=option,
            member=ballot_member
        )

        # Update cached vote count
        option.votes_count = models.F('votes_count') + 1
        option.save(update_fields=['votes_count'])

        return vote


def create_poll_with_options(
    title: str,
    poll_type: str,
    description: str,
    start_date,
    end_date,
    is_secret_ballot: bool,
    status: str,
    options_list: List[Dict[str, str]],
    created_by: Optional[User] = None
) -> Poll:
    """Creates a poll along with candidate choices/options in a single transaction."""
    if start_date > end_date:
        raise ValidationError("Voting start date cannot be later than end date.")

    if not options_list or len(options_list) < 2:
        raise ValidationError("At least two candidate choices or options are required.")

    with transaction.atomic():
        poll = Poll.objects.create(
            title=title.strip(),
            poll_type=poll_type,
            description=description.strip() if description else '',
            start_date=start_date,
            end_date=end_date,
            is_secret_ballot=is_secret_ballot,
            status=status,
            created_by=created_by
        )

        for index, opt_data in enumerate(options_list):
            text = opt_data.get('text', '').strip()
            desc = opt_data.get('description', '').strip()
            if text:
                PollOption.objects.create(
                    poll=poll,
                    text=text,
                    description=desc,
                    display_order=index + 1
                )

        return poll


def close_poll(poll: Poll, user: Optional[User] = None) -> Poll:
    """Closes an ongoing poll or election."""
    poll.status = PollStatus.CLOSED
    poll.save(update_fields=['status', 'updated_at'])
    return poll


def submit_member_feedback(
    member: Member,
    category: str,
    subject: str,
    message: str,
    rating: Optional[int] = None
) -> MemberFeedback:
    """Records a new grievance or suggestion from a member."""
    if member.is_removed:
        raise ValidationError("Cannot submit feedback: Member record is marked removed.")

    if rating is not None and (rating < 1 or rating > 5):
        raise ValidationError("Rating must be between 1 and 5.")

    return MemberFeedback.objects.create(
        member=member,
        category=category,
        subject=subject.strip(),
        message=message.strip(),
        rating=rating,
        status=FeedbackStatus.SUBMITTED
    )


def respond_to_feedback(
    feedback: MemberFeedback,
    admin_response: str,
    new_status: str,
    is_public: bool,
    user: User
) -> MemberFeedback:
    """Staff action to record official response and resolve feedback."""
    feedback.admin_response = admin_response.strip()
    feedback.status = new_status
    feedback.is_public = is_public
    feedback.responded_by = user
    feedback.responded_at = timezone.now()
    feedback.save(update_fields=[
        'admin_response', 'status', 'is_public',
        'responded_by', 'responded_at', 'updated_at'
    ])
    return feedback


def export_poll_results_csv(poll: Poll) -> str:
    """Exports poll/election results breakdown to CSV format."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Election/Poll Title', poll.title])
    writer.writerow(['Type', poll.get_poll_type_display()])
    writer.writerow(['Voting Period', f"{poll.start_date:%d-%m-%Y} to {poll.end_date:%d-%m-%Y}"])
    writer.writerow(['Status', poll.get_status_display()])
    writer.writerow(['Secret Ballot', 'Yes' if poll.is_secret_ballot else 'No'])
    writer.writerow(['Total Ballots Cast', poll.total_votes])
    writer.writerow([])
    writer.writerow(['Option / Candidate', 'Description / Bio', 'Votes Received', 'Percentage (%)'])

    options = poll.options.all().order_by('-votes_count')
    for opt in options:
        writer.writerow([
            opt.text,
            opt.description,
            opt.votes_count,
            f"{opt.vote_percentage}%"
        ])

    return output.getvalue()
