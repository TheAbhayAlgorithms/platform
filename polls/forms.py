from django import forms
from polls.models import (
    Poll,
    PollOption,
    PollType,
    PollStatus,
    MemberFeedback,
    FeedbackCategory,
    FeedbackStatus,
)


class PollForm(forms.ModelForm):
    class Meta:
        model = Poll
        fields = [
            'title', 'poll_type', 'description',
            'start_date', 'end_date', 'is_secret_ballot', 'status'
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Managing Committee Election 2026'}),
            'poll_type': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Guidelines, terms, or candidate qualifications...'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'is_secret_ballot': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
        }


class PollOptionForm(forms.ModelForm):
    class Meta:
        model = PollOption
        fields = ['text', 'description']
        widgets = {
            'text': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Candidate Name or Option Choice'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Bio / Designation / Notes'}),
        }


class FeedbackResponseForm(forms.ModelForm):
    class Meta:
        model = MemberFeedback
        fields = ['admin_response', 'status', 'is_public']
        widgets = {
            'admin_response': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Enter official Institute response or resolution details...'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'is_public': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class MemberFeedbackForm(forms.ModelForm):
    class Meta:
        model = MemberFeedback
        fields = ['category', 'subject', 'message', 'rating']
        widgets = {
            'category': forms.Select(attrs={'class': 'form-control'}),
            'subject': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Brief summary of suggestion or grievance'}),
            'message': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Detailed description...'}),
            'rating': forms.Select(
                choices=[('', '-- Optional Star Rating --'), (5, '★★★★★ Excellent (5/5)'), (4, '★★★★☆ Good (4/5)'), (3, '★★★☆☆ Average (3/5)'), (2, '★★☆☆☆ Poor (2/5)'), (1, '★☆☆☆☆ Critical (1/5)')],
                attrs={'class': 'form-control'}
            ),
        }
