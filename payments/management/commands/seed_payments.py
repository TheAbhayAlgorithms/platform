from decimal import Decimal
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from members.models import Member, MemberStatus
from payments.models import Payment, PaymentMode, PaymentStatus
from payments.services import record_payment, calculate_member_dues, sync_member_status_after_payment

class Command(BaseCommand):
    help = "Seeds demo payment records, partial payments, and receipts for members."

    def handle(self, *args, **options):
        accountant_user = User.objects.filter(username='accountant').first()

        members = Member.objects.all().order_by('id')
        if not members.exists():
            self.stdout.write(self.style.ERROR("No members found. Please run seed_members and seed_plans first."))
            return

        demo_payments = [
            # 1. Full Payment via UPI
            {
                'member_idx': 0,  # Ramesh Chandra Verma
                'amount': Decimal('3000.00'),
                'payment_mode': PaymentMode.UPI,
                'reference_number': 'UPI/2026/WR/884102941',
                'notes': 'Annual fee paid via GPay to institute QR code.',
            },
            # 2. Full Payment via Bank Transfer
            {
                'member_idx': 1,  # Pooja Kulkarni
                'amount': Decimal('3000.00'),
                'payment_mode': PaymentMode.BANK_TRANSFER,
                'reference_number': 'NEFT-SBI-0091823741',
                'notes': 'Online transfer from SBI Railway Branch account.',
            },
            # 3. Partial Payment via Cash (leaves balance due)
            {
                'member_idx': 2,  # Devendra Singh Rathore (Plan fee ₹1500)
                'amount': Decimal('500.00'),
                'payment_mode': PaymentMode.CASH,
                'reference_number': 'CASH-REC-01',
                'notes': 'Partial cash installment paid at institute accounts desk. Balance ₹1000 remaining.',
            },
            # 4. Full Payment via Cheque
            {
                'member_idx': 4,  # Kavita Sundaram
                'amount': Decimal('3000.00'),
                'payment_mode': PaymentMode.CHEQUE,
                'reference_number': 'CHQ-883921',
                'notes': 'Bank of Baroda Cheque No. 883921 deposited.',
            },
        ]

        count = 0
        for pdata in demo_payments:
            if pdata['member_idx'] < len(members):
                member = members[pdata['member_idx']]
                # Check if already paid
                if not member.payments.exists():
                    payment = record_payment(
                        member=member,
                        amount=pdata['amount'],
                        payment_mode=pdata['payment_mode'],
                        reference_number=pdata['reference_number'],
                        collected_by=accountant_user,
                        notes=pdata['notes'],
                    )
                    count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Recorded Payment {payment.receipt_number} for {member.name}: ₹{payment.amount:,.2f} ({payment.get_payment_mode_display()})"
                        )
                    )

        # Sync all member statuses
        for m in members:
            sync_member_status_after_payment(m)

        self.stdout.write(self.style.SUCCESS(f"Successfully seeded {count} demo payment transactions!"))
