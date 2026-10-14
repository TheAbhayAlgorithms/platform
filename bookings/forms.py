from django import forms
from decimal import Decimal
from bookings.models import Facility, HallBooking, BookingSlot, EventType


class FacilityForm(forms.ModelForm):
    class Meta:
        model = Facility
        fields = [
            'name', 'facility_type', 'capacity',
            'rent_per_slot', 'full_day_rent', 'security_deposit',
            'flat_electricity_charge', 'description', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Grand Banquet Hall'}),
            'facility_type': forms.Select(attrs={'class': 'form-control'}),
            'capacity': forms.NumberInput(attrs={'class': 'form-control', 'min': 10}),
            'rent_per_slot': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'full_day_rent': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'security_deposit': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'flat_electricity_charge': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Amenities, AC, generator backup...'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class StaffHallBookingForm(forms.Form):
    member_id = forms.IntegerField(widget=forms.HiddenInput())
    facility = forms.ModelChoiceField(
        queryset=Facility.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    booking_date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    slot = forms.ChoiceField(
        choices=BookingSlot.choices,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    event_type = forms.ChoiceField(
        choices=EventType.choices,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    purpose = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Wedding ceremony of daughter'})
    )
    advance_paid = forms.DecimalField(
        initial=Decimal('0.00'),
        min_value=Decimal('0.00'),
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
    )
    special_requests = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Catering vendor, DJ permissions, generator requirements...'})
    )


class MemberPortalBookingForm(forms.Form):
    facility = forms.ModelChoiceField(
        queryset=Facility.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    booking_date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    slot = forms.ChoiceField(
        choices=BookingSlot.choices,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    event_type = forms.ChoiceField(
        choices=EventType.choices,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    purpose = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Daughter marriage ceremony / Family reception'})
    )
    special_requests = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Special requests, external catering, decoration...'})
    )


class DepositRefundForm(forms.Form):
    refund_amount = forms.DecimalField(
        min_value=Decimal('0.00'),
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
    )
    notes = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Deductions (if any for cleaning or electrical damage)'})
    )
