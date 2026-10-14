from django import forms
from events.models import Event, EventCategory, EventStatus
from members.models import Member


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = [
            'title', 'category', 'description', 'venue',
            'start_date_time', 'end_date_time', 'registration_deadline',
            'capacity', 'member_entry_fee', 'guest_entry_fee',
            'max_guests_per_member', 'status', 'is_active'
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Diwali Milan 2026'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Event details, cultural schedule, instructions...'}),
            'venue': forms.TextInput(attrs={'class': 'form-control'}),
            'start_date_time': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'end_date_time': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'registration_deadline': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'capacity': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'member_entry_fee': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'guest_entry_fee': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'max_guests_per_member': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 20}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class StaffEventRegistrationForm(forms.Form):
    member_id = forms.IntegerField(
        widget=forms.HiddenInput()
    )
    num_family_members = forms.IntegerField(
        initial=0,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 0})
    )
    num_guests = forms.IntegerField(
        initial=0,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 0})
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Dietary, seating requests...'})
    )
