from decimal import Decimal
from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError


class FacilityType(models.TextChoices):
    BANQUET_HALL = 'BANQUET_HALL', 'Grand Banquet Hall'
    WEDDING_LAWN = 'WEDDING_LAWN', 'Open Wedding Lawns'
    COMMUNITY_HALL = 'COMMUNITY_HALL', 'Community Dining & Multi-Purpose Hall'
    AUDITORIUM = 'AUDITORIUM', 'Main Auditorium'
    CONFERENCE_ROOM = 'CONFERENCE_ROOM', 'Conference & Meeting Room'


class Facility(models.Model):
    """
    Institute venues, banquet halls, and wedding grounds available for hire.
    Stores base subsidized rents for railway staff, damage deposits, and amenities.
    """
    name = models.CharField(
        max_length=120,
        unique=True,
        help_text="Facility name (e.g. Grand Banquet Hall, Open Wedding Lawns)."
    )
    facility_type = models.CharField(
        max_length=30,
        choices=FacilityType.choices,
        default=FacilityType.BANQUET_HALL,
        db_index=True
    )
    capacity = models.PositiveIntegerField(
        default=200,
        help_text="Recommended maximum guest capacity."
    )
    rent_per_slot = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('5000.00'),
        help_text="Subsidized rent for half-day morning or evening slot in INR (₹)."
    )
    full_day_rent = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('9000.00'),
        help_text="Subsidized rent for full-day booking in INR (₹)."
    )
    security_deposit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('2000.00'),
        help_text="Refundable damage and cleaning security deposit in INR (₹)."
    )
    flat_electricity_charge = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('1000.00'),
        help_text="Electricity, AC, and generator backup charges in INR (₹)."
    )
    description = models.TextField(
        blank=True,
        help_text="Amenities, sound system, green rooms, kitchen, and decoration guidelines."
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Active facilities available for booking."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Facility / Hall"
        verbose_name_plural = "Facilities & Halls"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} (Cap: {self.capacity})"


class BookingSlot(models.TextChoices):
    MORNING = 'MORNING', 'Morning Slot (08:00 AM - 02:00 PM)'
    EVENING = 'EVENING', 'Evening Slot (04:00 PM - 11:00 PM)'
    FULL_DAY = 'FULL_DAY', 'Full Day (08:00 AM - 11:00 PM)'


class EventType(models.TextChoices):
    WEDDING = 'WEDDING', 'Wedding Ceremony / Marriage'
    RECEPTION = 'RECEPTION', 'Wedding Reception'
    ENGAGEMENT = 'ENGAGEMENT', 'Ring Ceremony / Engagement'
    BIRTHDAY = 'BIRTHDAY', 'Birthday Celebration'
    RETIREMENT = 'RETIREMENT', 'Railway Retirement Farewell'
    RELIGIOUS = 'RELIGIOUS', 'Puja / Religious Gathering'
    OTHER = 'OTHER', 'Other Family & Social Function'


class BookingStatus(models.TextChoices):
    REQUESTED = 'REQUESTED', 'Requested (Pending Staff Review)'
    CONFIRMED = 'CONFIRMED', 'Confirmed & Reserved'
    COMPLETED = 'COMPLETED', 'Completed'
    CANCELLED = 'CANCELLED', 'Cancelled'
    REJECTED = 'REJECTED', 'Declined / Rejected'


class PaymentStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending Payment'
    ADVANCE_PAID = 'ADVANCE_PAID', 'Advance Paid'
    FULLY_PAID = 'FULLY_PAID', 'Fully Paid'
    REFUNDED = 'REFUNDED', 'Refunded'


class HallBooking(models.Model):
    """
    Wedding and community hall reservation record.
    Prevents conflicting double-bookings, preserves financial snapshots,
    and manages security deposit refunds.
    """
    booking_id = models.CharField(
        max_length=25,
        unique=True,
        db_index=True,
        help_text="Sequential booking identifier (e.g. HB-2026-00001)."
    )
    facility = models.ForeignKey(
        Facility,
        on_delete=models.PROTECT,
        related_name='bookings'
    )
    member = models.ForeignKey(
        'members.Member',
        on_delete=models.CASCADE,
        related_name='hall_bookings'
    )
    event_type = models.CharField(
        max_length=30,
        choices=EventType.choices,
        default=EventType.WEDDING
    )
    purpose = models.CharField(
        max_length=200,
        help_text="Description of the function (e.g., Wedding ceremony of daughter Ananya)."
    )
    booking_date = models.DateField(
        db_index=True,
        help_text="Date the facility is reserved for."
    )
    slot = models.CharField(
        max_length=20,
        choices=BookingSlot.choices,
        default=BookingSlot.EVENING
    )
    # Financial snapshot
    rent_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Base hall rent."
    )
    deposit_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Refundable security deposit."
    )
    electricity_charges = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Electricity / generator backup charge."
    )
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Grand total payable (rent + deposit + electricity)."
    )
    advance_paid = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Advance token amount received."
    )
    # Deposit refund tracking
    deposit_refunded = models.BooleanField(
        default=False,
        help_text="True if refundable security deposit has been returned to member."
    )
    deposit_refund_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Actual amount refunded after any damage/cleaning deductions."
    )
    deposit_refund_date = models.DateField(
        null=True,
        blank=True
    )
    status = models.CharField(
        max_length=20,
        choices=BookingStatus.choices,
        default=BookingStatus.CONFIRMED,
        db_index=True
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING
    )
    cancellation_reason = models.TextField(
        blank=True,
        help_text="Audit explanation if booking was cancelled or rejected."
    )
    special_requests = models.TextField(
        blank=True,
        help_text="Catering arrangements, stage setup, music/DJ permissions."
    )
    approved_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='approved_hall_bookings'
    )
    booked_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hall / Wedding Booking"
        verbose_name_plural = "Hall & Wedding Bookings"
        ordering = ['-booking_date', '-booked_at']
        indexes = [
            models.Index(fields=['facility', 'booking_date', 'status']),
            models.Index(fields=['member', 'status']),
            models.Index(fields=['booking_date', 'slot']),
        ]

    def __str__(self):
        return f"{self.booking_id} - {self.facility.name} ({self.booking_date:%d-%m-%Y} {self.get_slot_display()})"

    @classmethod
    def generate_next_booking_id(cls, year: int = None) -> str:
        """
        Thread-safe generation of next sequential booking reference: HB-YYYY-NNNNN.
        """
        if year is None:
            year = timezone.now().year

        prefix = f"HB-{year}-"
        with transaction.atomic():
            latest = cls.objects.select_for_update().filter(
                booking_id__startswith=prefix
            ).order_by('-booking_id').first()

            if latest:
                try:
                    num_part = int(latest.booking_id.split('-')[-1])
                    next_num = num_part + 1
                except (ValueError, IndexError):
                    next_num = 1
            else:
                next_num = 1

            return f"{prefix}{next_num:05d}"

    def save(self, *args, **kwargs):
        if not self.booking_id:
            self.booking_id = self.generate_next_booking_id(self.booking_date.year if self.booking_date else None)
        super().save(*args, **kwargs)

    @property
    def balance_amount(self) -> Decimal:
        return max(Decimal('0.00'), self.total_amount - self.advance_paid)

    @property
    def balance_due(self) -> Decimal:
        return self.balance_amount
