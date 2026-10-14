from django.contrib import admin
from bookings.models import Facility, HallBooking


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ('name', 'facility_type', 'capacity', 'rent_per_slot', 'full_day_rent', 'security_deposit', 'is_active')
    list_filter = ('facility_type', 'is_active')
    search_fields = ('name', 'description')


@admin.register(HallBooking)
class HallBookingAdmin(admin.ModelAdmin):
    list_display = ('booking_id', 'facility', 'member', 'booking_date', 'slot', 'event_type', 'status', 'payment_status', 'total_amount')
    list_filter = ('status', 'payment_status', 'slot', 'event_type', 'facility')
    search_fields = ('booking_id', 'member__name', 'member__membership_id', 'purpose')
    date_hierarchy = 'booking_date'
