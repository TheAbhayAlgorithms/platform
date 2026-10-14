from decimal import Decimal
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from payments.models import Payment, PaymentAdjustment, PaymentMode, AdjustmentType

class PaymentRecordForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = [
            'amount',
            'payment_date',
            'payment_mode',
            'reference_number',
            'notes',
        ]
        widgets = {
            'payment_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Optional remarks or Cheque Bank details'}),
        }

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is None or amount <= Decimal('0.00'):
            raise ValidationError("Payment amount must be greater than zero.")
        return amount

    def clean(self):
        cleaned_data = super().clean()
        mode = cleaned_data.get('payment_mode')
        ref = cleaned_data.get('reference_number', '').strip()

        # For UPI, Bank Transfer, Cheque, reference number is strongly recommended
        if mode in [PaymentMode.UPI, PaymentMode.BANK_TRANSFER, PaymentMode.CHEQUE] and not ref:
            self.add_error('reference_number', f"Reference number (UTR / Cheque No) is required for {dict(PaymentMode.choices).get(mode)}.")

        return cleaned_data


class PaymentCancelForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'State mandatory reason for cancelling this payment (e.g. cheque bounced, transaction reversal, incorrect entry)'}),
        required=True,
        help_text="Mandatory audit justification for revoking this financial transaction."
    )


class PaymentAdjustmentForm(forms.ModelForm):
    class Meta:
        model = PaymentAdjustment
        fields = ['adjustment_type', 'amount', 'reason']
        widgets = {
            'reason': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Mandatory audit explanation for this adjustment or refund.'}),
        }

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is None or amount <= Decimal('0.00'):
            raise ValidationError("Adjustment amount must be greater than zero.")
        return amount
