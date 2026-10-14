from decimal import Decimal
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from members.models import Member, MemberStatus
from plans.models import Plan, DiscountConcession, MemberPlanAssignment, LateFeeType, DiscountType

class Command(BaseCommand):
    help = "Seeds standard membership plans, discount categories, and assigns plans to demo members."

    def handle(self, *args, **options):
        # 1. Seed Plans
        plans_data = [
            {
                'name': 'Annual Membership',
                'description': 'Full access to railway club facilities, annual day festivities, sports pavilion, and member rates for wedding lawn bookings.',
                'fee': Decimal('3000.00'),
                'duration_months': 12,
                'duration_days': 0,
                'grace_period_days': 15,
                'late_fee_type': LateFeeType.FLAT,
                'late_fee_amount': Decimal('100.00'),
                'is_active': True,
            },
            {
                'name': 'Half-Yearly Membership',
                'description': 'Bi-annual club membership covering Navaratri and Diwali celebrations with standard club amenities.',
                'fee': Decimal('1800.00'),
                'duration_months': 6,
                'duration_days': 0,
                'grace_period_days': 10,
                'late_fee_type': LateFeeType.FLAT,
                'late_fee_amount': Decimal('50.00'),
                'is_active': True,
            },
            {
                'name': 'Quarterly Membership',
                'description': 'Three-month trial or seasonal membership with per-day late fee policy.',
                'fee': Decimal('1000.00'),
                'duration_months': 3,
                'duration_days': 0,
                'grace_period_days': 7,
                'late_fee_type': LateFeeType.PER_DAY,
                'late_fee_amount': Decimal('10.00'),
                'is_active': True,
            },
            {
                'name': 'Festival & Event Special (1 Month)',
                'description': 'Short-term pass for festive cultural celebrations (Navaratri Garba, Diwali Sneh Milan).',
                'fee': Decimal('500.00'),
                'duration_months': 1,
                'duration_days': 0,
                'grace_period_days': 5,
                'late_fee_type': LateFeeType.NONE,
                'late_fee_amount': Decimal('0.00'),
                'is_active': True,
            },
        ]

        created_plans = {}
        for pdata in plans_data:
            plan, created = Plan.objects.get_or_create(
                name=pdata['name'],
                defaults=pdata
            )
            created_plans[plan.name] = plan
            act = "Created" if created else "Found"
            self.stdout.write(self.style.SUCCESS(f"{act} Plan: {plan.name} - ₹{plan.fee:,.2f}"))

        # 2. Seed Discounts
        discounts_data = [
            {
                'name': 'Retired Railway Employee Concession (50%)',
                'description': 'Special 50% concession for superannuated railway employees and railway pensioners.',
                'discount_type': DiscountType.PERCENTAGE,
                'discount_value': Decimal('50.00'),
                'is_active': True,
            },
            {
                'name': 'Senior Citizen Discount (₹300 Flat)',
                'description': 'Flat ₹300 fee deduction for railway family senior citizens.',
                'discount_type': DiscountType.FLAT,
                'discount_value': Decimal('300.00'),
                'is_active': True,
            },
        ]

        created_discounts = {}
        for ddata in discounts_data:
            disc, created = DiscountConcession.objects.get_or_create(
                name=ddata['name'],
                defaults=ddata
            )
            created_discounts[disc.name] = disc
            act = "Created" if created else "Found"
            self.stdout.write(self.style.SUCCESS(f"{act} Discount: {disc.name}"))

        # 3. Assign plans to seeded members if not already assigned
        members = Member.objects.all()
        annual_plan = created_plans.get('Annual Membership')
        retired_disc = created_discounts.get('Retired Railway Employee Concession (50%)')

        for idx, member in enumerate(members):
            if not member.plan_assignments.exists():
                # Stagger start dates to demonstrate active, due, and expired states
                if member.status == MemberStatus.EXPIRED:
                    start = timezone.now().date() - timedelta(days=400)
                elif member.status == MemberStatus.DUE:
                    start = timezone.now().date() - timedelta(days=366)
                else:
                    start = timezone.now().date() - timedelta(days=60)

                disc = retired_disc if idx == 0 else None
                assignment = MemberPlanAssignment.objects.create(
                    member=member,
                    plan=annual_plan,
                    discount=disc,
                    start_date=start,
                    is_current=True,
                    notes=f"Auto-assigned initial plan during demo setup."
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Assigned {assignment.plan.name} to {member.name} (Valid: {assignment.start_date:%d-%m-%Y} to {assignment.end_date:%d-%m-%Y}, Fee: ₹{assignment.final_fee})"
                    )
                )

        self.stdout.write(self.style.SUCCESS("Successfully seeded Module 3 plans and assignments!"))
