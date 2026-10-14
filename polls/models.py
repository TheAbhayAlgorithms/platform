from decimal import Decimal
from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError


class PollType(models.TextChoices):
    ELECTION = 'ELECTION', 'Managing Committee Election'
    OPINION_POLL = 'OPINION_POLL', 'Institute Opinion Poll'
    RESOLUTION = 'RESOLUTION', 'AGM Resolution / Policy Vote'
    SURVEY = 'SURVEY', 'Feedback & Amenities Survey'


class PollStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    OPEN = 'OPEN', 'Voting Open'
    CLOSED = 'CLOSED', 'Voting Closed'
    ARCHIVED = 'ARCHIVED', 'Archived'


class Poll(models.Model):
    """
    Institute elections, member opinion polls, and AGM resolutions.
    Enforces active membership criteria, secret ballot anonymity,
    and strict single-vote rules per member.
    """
    title = models.CharField(
        max_length=200,
        help_text="Title of the election or poll (e.g. Managing Committee Election 2026)."
    )
    poll_type = models.CharField(
        max_length=30,
        choices=PollType.choices,
        default=PollType.OPINION_POLL,
        db_index=True
    )
    description = models.TextField(
        blank=True,
        help_text="Detailed instructions, election manifesto guidelines, or poll context."
    )
    start_date = models.DateField(
        help_text="Date on which voting opens."
    )
    end_date = models.DateField(
        help_text="Date on which voting closes."
    )
    is_secret_ballot = models.BooleanField(
        default=True,
        help_text="If True, individual voter identity is unlinked from the selected candidate/option."
    )
    status = models.CharField(
        max_length=20,
        choices=PollStatus.choices,
        default=PollStatus.DRAFT,
        db_index=True
    )
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='created_polls'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Poll / Election"
        verbose_name_plural = "Polls & Elections"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.get_poll_type_display()}) [{self.get_status_display()}]"

    def clean(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValidationError({'end_date': "End date cannot be earlier than start date."})

    @property
    def is_active_for_voting(self) -> bool:
        today = timezone.now().date()
        return self.status == PollStatus.OPEN and self.start_date <= today <= self.end_date

    @property
    def total_votes(self) -> int:
        return self.voters.count()

    def get_leading_option(self):
        return self.options.order_by('-votes_count').first()


class PollOption(models.Model):
    """
    Candidates or choices available for a given election or poll.
    """
    poll = models.ForeignKey(
        Poll,
        on_delete=models.CASCADE,
        related_name='options'
    )
    text = models.CharField(
        max_length=200,
        help_text="Candidate name or choice title."
    )
    description = models.TextField(
        blank=True,
        help_text="Candidate bio / designation or explanation of option."
    )
    votes_count = models.PositiveIntegerField(
        default=0,
        help_text="Cached count of votes received."
    )
    display_order = models.PositiveIntegerField(
        default=0,
        help_text="Display order on ballot form."
    )

    class Meta:
        verbose_name = "Poll Option / Candidate"
        verbose_name_plural = "Poll Options / Candidates"
        ordering = ['display_order', 'id']

    def __str__(self):
        return f"{self.poll.title} - {self.text}"

    @property
    def vote_percentage(self) -> float:
        total = self.poll.total_votes
        if total == 0:
            return 0.0
        return round((self.votes_count / total) * 100, 1)


class PollVoter(models.Model):
    """
    Audits member participation to strictly prevent double voting.
    Stored independently of the Vote record when secret ballot is active.
    """
    poll = models.ForeignKey(
        Poll,
        on_delete=models.CASCADE,
        related_name='voters'
    )
    member = models.ForeignKey(
        'members.Member',
        on_delete=models.CASCADE,
        related_name='participated_polls'
    )
    voted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Poll Voter Audit"
        verbose_name_plural = "Poll Voter Audits"
        unique_together = ('poll', 'member')
        ordering = ['-voted_at']

    def __str__(self):
        return f"{self.member.name} voted in {self.poll.title} on {self.voted_at:%d-%m-%Y %H:%M}"


class Vote(models.Model):
    """
    Recorded ballot choice. If the poll is marked secret ballot,
    the member field is NULL to ensure confidentiality.
    """
    poll = models.ForeignKey(
        Poll,
        on_delete=models.CASCADE,
        related_name='ballots'
    )
    option = models.ForeignKey(
        PollOption,
        on_delete=models.CASCADE,
        related_name='ballots'
    )
    member = models.ForeignKey(
        'members.Member',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='cast_votes',
        help_text="Null for secret ballots; populated for open non-confidential surveys."
    )
    voted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Cast Ballot"
        verbose_name_plural = "Cast Ballots"
        ordering = ['-voted_at']

    def __str__(self):
        return f"Vote for {self.option.text} in {self.poll.title}"


# =========================================================================
# MEMBER FEEDBACK & COMPLAINTS SYSTEM
# =========================================================================

class FeedbackCategory(models.TextChoices):
    CANTEEN = 'CANTEEN', 'Canteen & Dining'
    SPORTS = 'SPORTS', 'Sports & Gym Facilities'
    LIBRARY = 'LIBRARY', 'Library & Reading Room'
    MAINTENANCE = 'MAINTENANCE', 'Cleanliness & Campus Maintenance'
    EVENTS = 'EVENTS', 'Festival & Cultural Programs'
    GOVERNANCE = 'GOVERNANCE', 'Institute Administration & Staff'
    OTHER = 'OTHER', 'General Suggestion / Other'


class FeedbackStatus(models.TextChoices):
    SUBMITTED = 'SUBMITTED', 'Submitted'
    UNDER_REVIEW = 'UNDER_REVIEW', 'Under Review'
    RESOLVED = 'RESOLVED', 'Addressed & Resolved'
    CLOSED = 'CLOSED', 'Closed'


class MemberFeedback(models.Model):
    """
    Feedback, grievance, and suggestion submitted by railway club members.
    Tracks review lifecycle, official administrative response, and resolution.
    """
    member = models.ForeignKey(
        'members.Member',
        on_delete=models.CASCADE,
        related_name='feedbacks'
    )
    category = models.CharField(
        max_length=30,
        choices=FeedbackCategory.choices,
        default=FeedbackCategory.OTHER,
        db_index=True
    )
    subject = models.CharField(
        max_length=200,
        help_text="Brief subject or title of the feedback."
    )
    message = models.TextField(
        help_text="Detailed suggestion, compliment, or complaint."
    )
    rating = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Optional satisfaction rating from 1 to 5."
    )
    status = models.CharField(
        max_length=20,
        choices=FeedbackStatus.choices,
        default=FeedbackStatus.SUBMITTED,
        db_index=True
    )
    admin_response = models.TextField(
        blank=True,
        help_text="Official administrative response or action taken."
    )
    responded_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='responded_feedbacks'
    )
    responded_at = models.DateTimeField(
        null=True,
        blank=True
    )
    is_public = models.BooleanField(
        default=False,
        help_text="Visible to other members on the public suggestions board."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Member Feedback / Grievance"
        verbose_name_plural = "Member Feedbacks & Grievances"
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_category_display()}] {self.subject} ({self.member.name})"

    def clean(self):
        if self.rating is not None and (self.rating < 1 or self.rating > 5):
            raise ValidationError({'rating': "Rating must be an integer between 1 and 5."})
