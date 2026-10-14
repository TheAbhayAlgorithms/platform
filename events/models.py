from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError


class EventCategory(models.TextChoices):
    FESTIVAL = 'FESTIVAL', 'Festival Celebration (Diwali, Holi, Durga Puja, etc.)'
    CULTURAL = 'CULTURAL', 'Cultural Evening & Musical Night'
    NATIONAL_DAY = 'NATIONAL_DAY', 'National Day (Republic Day / Independence Day)'
    SPORTS = 'SPORTS', 'Annual Sports Meet & Tournaments'
    ANNUAL_MEET = 'ANNUAL_MEET', 'Annual General Meeting / Institute Day'
    SOCIAL = 'SOCIAL', 'Social & Children Workshop'


class EventStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft / Planning'
    PUBLISHED = 'PUBLISHED', 'Published / Open for RSVP'
    ONGOING = 'ONGOING', 'Happening Today'
    COMPLETED = 'COMPLETED', 'Completed'
    CANCELLED = 'CANCELLED', 'Cancelled'


class Event(models.Model):
    """
    Railway Institute festival celebrations, cultural programs, and sports events.
    Tracks venue, date-time intervals, capacity, ticketing fees, and attendee RSVP limits.
    """
    title = models.CharField(
        max_length=150,
        help_text="Event title (e.g. Diwali Milan 2026, Independence Day Cultural Evening)."
    )
    category = models.CharField(
        max_length=40,
        choices=EventCategory.choices,
        default=EventCategory.FESTIVAL,
        db_index=True
    )
    description = models.TextField(
        blank=True,
        help_text="Detailed event schedule, dress code, and special instructions."
    )
    venue = models.CharField(
        max_length=150,
        default="Institute Main Auditorium & Lawns",
        help_text="Venue inside or affiliated with the Railway Institute."
    )
    start_date_time = models.DateTimeField(
        help_text="Scheduled start date and time."
    )
    end_date_time = models.DateTimeField(
        help_text="Scheduled end date and time."
    )
    registration_deadline = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last date and time for members to RSVP / register."
    )
    capacity = models.PositiveIntegerField(
        default=0,
        help_text="Maximum total headcount capacity (0 for unlimited attendees)."
    )
    member_entry_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Subsidized entry fee for railway employee member in INR (₹) (0 for free)."
    )
    guest_entry_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Entry fee per accompanying guest/non-member in INR (₹)."
    )
    max_guests_per_member = models.PositiveIntegerField(
        default=4,
        help_text="Maximum non-member guests allowed per registered member."
    )
    status = models.CharField(
        max_length=20,
        choices=EventStatus.choices,
        default=EventStatus.PUBLISHED,
        db_index=True
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Controls visibility across the platform and member portal."
    )
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='created_events'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Festival / Event"
        verbose_name_plural = "Festival & Events"
        ordering = ['start_date_time']
        indexes = [
            models.Index(fields=['status', 'start_date_time']),
            models.Index(fields=['category', 'start_date_time']),
        ]

    def __str__(self):
        return f"{self.title} ({self.start_date_time:%d-%m-%Y %H:%M})"

    def clean(self):
        super().clean()
        if self.start_date_time and self.end_date_time:
            if self.end_date_time <= self.start_date_time:
                raise ValidationError({
                    'end_date_time': "Event end time must be strictly after the start time."
                })
        if self.registration_deadline and self.start_date_time:
            if self.registration_deadline > self.start_date_time:
                raise ValidationError({
                    'registration_deadline': "Registration deadline cannot be after the event start time."
                })

    @property
    def is_registration_open(self) -> bool:
        now = timezone.now()
        if not self.is_active or self.status != EventStatus.PUBLISHED:
            return False
        if now >= self.end_date_time:
            return False
        if self.registration_deadline and now > self.registration_deadline:
            return False
        if self.is_full:
            return False
        return True

    @property
    def registered_headcount(self) -> int:
        """Returns the total number of people (members + family + guests) confirmed."""
        total = 0
        for reg in self.registrations.filter(status=RegistrationStatus.CONFIRMED):
            total += (1 + reg.num_family_members + reg.num_guests)
        return total

    @property
    def checked_in_headcount(self) -> int:
        """Returns the total number of attendees actually checked in at the event."""
        total = 0
        for reg in self.registrations.filter(status=RegistrationStatus.CONFIRMED, checked_in=True):
            total += (1 + reg.num_family_members + reg.num_guests)
        return total

    @property
    def remaining_capacity(self) -> int:
        if self.capacity == 0:
            return 999999  # unlimited
        return max(0, self.capacity - self.registered_headcount)

    @property
    def is_full(self) -> bool:
        if self.capacity == 0:
            return False
        return self.registered_headcount >= self.capacity


class RegistrationStatus(models.TextChoices):
    CONFIRMED = 'CONFIRMED', 'Confirmed'
    CANCELLED = 'CANCELLED', 'Cancelled'


class EventPaymentStatus(models.TextChoices):
    FREE = 'FREE', 'Free Entry'
    PAID = 'PAID', 'Paid'
    PENDING = 'PENDING', 'Payment Pending'


class EventRegistration(models.Model):
    """
    Member RSVP / ticket registration record for an institute event.
    Captures accompanying family headcount, non-member guests, entry fees, and venue check-in.
    """
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='registrations'
    )
    member = models.ForeignKey(
        'members.Member',
        on_delete=models.CASCADE,
        related_name='event_registrations'
    )
    num_family_members = models.PositiveIntegerField(
        default=0,
        help_text="Number of registered family dependants attending."
    )
    num_guests = models.PositiveIntegerField(
        default=0,
        help_text="Number of accompanying outside guests."
    )
    calculated_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total entry fee payable (member fee + guests fee)."
    )
    payment_status = models.CharField(
        max_length=20,
        choices=EventPaymentStatus.choices,
        default=EventPaymentStatus.FREE
    )
    status = models.CharField(
        max_length=20,
        choices=RegistrationStatus.choices,
        default=RegistrationStatus.CONFIRMED,
        db_index=True
    )
    checked_in = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Venue gate arrival check-in verification."
    )
    checked_in_at = models.DateTimeField(
        null=True,
        blank=True
    )
    notes = models.TextField(
        blank=True,
        help_text="Special requests (dietary, seating, senior citizen assistance)."
    )
    registered_at = models.DateTimeField(auto_now_add=True)
    registered_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='staff_registered_events',
        help_text="Staff user who recorded registration (None if member self-registered)."
    )

    class Meta:
        verbose_name = "Event Registration"
        verbose_name_plural = "Event Registrations"
        ordering = ['-registered_at']
        indexes = [
            models.Index(fields=['event', 'status']),
            models.Index(fields=['member', 'status']),
        ]

    def __str__(self):
        return f"{self.member.name} -> {self.event.title} ({self.total_headcount} attendees)"

    @property
    def total_headcount(self) -> int:
        return 1 + self.num_family_members + self.num_guests
