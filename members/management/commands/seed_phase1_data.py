from datetime import date, timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from django.db import transaction

from accounts.models import UserProfile, RoleChoices
from core.encryption import compute_blind_index, normalize_phone
from members.models import Member, MemberFamily, MemberStatus, DepartmentChoices
from plans.models import Plan, DiscountConcession, DiscountType, MemberPlanAssignment
from payments.models import Payment, PaymentMode, PaymentStatus
from renewals.models import RenewalRecord


class Command(BaseCommand):
    help = "Seeds comprehensive hardened Phase 1 dataset: 50 realistic railway members, plans, payments, family dependents, and renewal histories."

    def add_arguments(self, parser):
        parser.add_argument(
            '--clean',
            action='store_true',
            help='Wipe existing demo member and payment data before seeding.'
        )

    def handle(self, *args, **options):
        if options.get('clean'):
            self.stdout.write(self.style.WARNING("Cleaning existing demo member, plan, and payment records..."))
            with transaction.atomic():
                RenewalRecord.objects.all().delete()
                Payment.objects.all().delete()
                MemberPlanAssignment.objects.all().delete()
                MemberFamily.objects.all().delete()
                Member.objects.all().delete()

        self.stdout.write("Hardening base administrative accounts...")
        admin_user, _ = User.objects.get_or_create(
            username='superadmin',
            defaults={'email': 'admin@railclub.test', 'first_name': 'Chief', 'last_name': 'Admin'}
        )
        if not admin_user.has_usable_password():
            admin_user.set_password('Admin@RailClub2026!')
            admin_user.save()
        UserProfile.objects.get_or_create(
            user=admin_user,
            defaults={'role': RoleChoices.SUPER_ADMIN, 'phone': '+919876543210'}
        )

        acct_user, _ = User.objects.get_or_create(
            username='accountant',
            defaults={'email': 'acct@railclub.test', 'first_name': 'Senior', 'last_name': 'Accountant'}
        )
        if not acct_user.has_usable_password():
            acct_user.set_password('Acct@RailClub2026!')
            acct_user.save()
        UserProfile.objects.get_or_create(
            user=acct_user,
            defaults={'role': RoleChoices.ACCOUNTANT, 'phone': '+919876543211'}
        )

        # Plans
        self.stdout.write("Ensuring standard membership plans exist...")
        annual_plan, _ = Plan.objects.get_or_create(
            name="Annual Membership Plan",
            defaults={
                'fee': Decimal('2400.00'),
                'duration_months': 12,
                'grace_period_days': 15,
                'description': 'Full annual access to Institute facilities, library, sports complex, and all festival passes.'
            }
        )
        half_yearly_plan, _ = Plan.objects.get_or_create(
            name="Half-Yearly Membership Plan",
            defaults={
                'fee': Decimal('1300.00'),
                'duration_months': 6,
                'grace_period_days': 10,
                'description': '6-month membership covering seasonal institute sports and cultural programs.'
            }
        )
        quarterly_plan, _ = Plan.objects.get_or_create(
            name="Quarterly Membership Plan",
            defaults={
                'fee': Decimal('750.00'),
                'duration_months': 3,
                'grace_period_days': 7,
                'description': '3-month trial or temporary post membership.'
            }
        )
        festival_plan, _ = Plan.objects.get_or_create(
            name="Festival-Only Cultural Pass",
            defaults={
                'fee': Decimal('500.00'),
                'duration_months': 1,
                'grace_period_days': 0,
                'description': 'Special event pass for Navaratri, Diwali, and Annual Cultural Fest.'
            }
        )

        senior_concession, _ = DiscountConcession.objects.get_or_create(
            name="Senior Railway Employee Concession",
            defaults={
                'discount_type': DiscountType.FLAT,
                'discount_value': Decimal('400.00'),
                'is_active': True
            }
        )

        # 50 Detailed Railway Members
        # Distribution: 30 Active, 10 Due, 5 Expired, 3 Removed, 2 Suspended
        raw_members_data = [
            # 1 to 10: Active
            ("Rajesh Chandra Sharma", "WR-ENG-1001", DepartmentChoices.ENGINEERING, MemberStatus.ACTIVE, "Senior Section Engineer, Bandra", [("Sangeeta Sharma", "SPOUSE", 45), ("Aryan Sharma", "SON", 16)]),
            ("Pooja Makarand Kulkarni", "CR-COM-2002", DepartmentChoices.COMMERCIAL, MemberStatus.ACTIVE, "Chief Commercial Inspector, CSMT", [("Makarand Kulkarni", "SPOUSE", 48), ("Tanvi Kulkarni", "DAUGHTER", 14)]),
            ("Mohammed Farooq Khan", "WR-MEC-3003", DepartmentChoices.MECHANICAL, MemberStatus.ACTIVE, "Loco Workshop Superintendent, Parel", [("Nasreen Khan", "SPOUSE", 42), ("Imran Khan", "SON", 19)]),
            ("Suresh Narayan Patel", "WR-OPS-4004", DepartmentChoices.OPERATING, MemberStatus.ACTIVE, "Chief Station Master, Dadar", [("Geeta Patel", "SPOUSE", 52), ("Dhaval Patel", "SON", 24)]),
            ("Anita Raman Nair", "SR-ACC-5005", DepartmentChoices.ACCOUNTS, MemberStatus.ACTIVE, "Senior Accounts Officer, FA&CAO Office", [("Raman Nair", "SPOUSE", 50)]),
            ("Vikram Jitendra Singh", "NR-RPF-6006", DepartmentChoices.SECURITY_RPF, MemberStatus.ACTIVE, "RPF Inspector, Central Railway", [("Meenakshi Singh", "SPOUSE", 39), ("Yash Singh", "SON", 11)]),
            ("Dinesh Kashinath Jadhav", "CR-ELE-7007", DepartmentChoices.ELECTRICAL, MemberStatus.ACTIVE, "Traction Power Controller, Kalyan", [("Swati Jadhav", "SPOUSE", 43), ("Rohit Jadhav", "SON", 18)]),
            ("Kavita Sundaram Iyer", "SR-MED-8008", DepartmentChoices.MEDICAL, MemberStatus.ACTIVE, "Chief Medical Matron, Byculla Railway Hospital", [("Sundaram Iyer", "SPOUSE", 55)]),
            ("Arun Babulal Meena", "WCR-SNT-9009", DepartmentChoices.SIGNAL_TELECOM, MemberStatus.ACTIVE, "Senior Divisional Signal Engineer, Kurla", [("Kamla Meena", "SPOUSE", 37), ("Pooja Meena", "DAUGHTER", 9)]),
            ("Gurpreet Singh Sodhi", "NR-PER-1010", DepartmentChoices.PERSONNEL, MemberStatus.ACTIVE, "Divisional Personnel Officer, Mumbai Central", [("Harpreet Kaur", "SPOUSE", 46), ("Simran Kaur", "DAUGHTER", 20)]),

            # 11 to 20: Active
            ("Manoj Prabhakar Joshi", "CR-STO-1111", DepartmentChoices.STORES, MemberStatus.ACTIVE, "Depot Material Superintendent, Matunga", [("Sunita Joshi", "SPOUSE", 51)]),
            ("Ashok Kumar Tiwari", "NCR-ENG-1212", DepartmentChoices.ENGINEERING, MemberStatus.ACTIVE, "Track Machine Operator, Thane", [("Shanti Tiwari", "SPOUSE", 40), ("Amit Tiwari", "SON", 15)]),
            ("Preeti Bhaskar Deshmukh", "CR-COM-1313", DepartmentChoices.COMMERCIAL, MemberStatus.ACTIVE, "Reservation Supervisor, Churchgate", [("Bhaskar Deshmukh", "SPOUSE", 47)]),
            ("Santosh Narayan Gaikwad", "WR-OPS-1414", DepartmentChoices.OPERATING, MemberStatus.ACTIVE, "Guard Special Grade, Borivali", [("Mangala Gaikwad", "SPOUSE", 44), ("Akash Gaikwad", "SON", 21)]),
            ("Rameshwar Dayal Meena", "NWR-ELE-1515", DepartmentChoices.ELECTRICAL, MemberStatus.ACTIVE, "AC Coach In-Charge, Mumbai Central", [("Lalita Meena", "SPOUSE", 38)]),
            ("Harishchandra Rao", "SCR-SNT-1616", DepartmentChoices.SIGNAL_TELECOM, MemberStatus.ACTIVE, "Telecom Maintainer Grade I, Vidyavihar", [("Padma Rao", "SPOUSE", 49), ("Srinivas Rao", "SON", 22)]),
            ("Deepak Vasant Shinde", "CR-MEC-1717", DepartmentChoices.MECHANICAL, MemberStatus.ACTIVE, "Carriage & Wagon Inspector, Wadi Bunder", [("Asha Shinde", "SPOUSE", 41)]),
            ("Bhavna Kishor Solanki", "WR-PER-1818", DepartmentChoices.PERSONNEL, MemberStatus.ACTIVE, "Welfare Inspector, Divisional Office", [("Kishor Solanki", "SPOUSE", 44)]),
            ("Raghunath Baburao Patil", "CR-RPF-1919", DepartmentChoices.SECURITY_RPF, MemberStatus.ACTIVE, "Assistant Sub-Inspector, Panvel RPF Post", [("Laxmi Patil", "SPOUSE", 53), ("Vikas Patil", "SON", 26)]),
            ("Sunil Jagdish Chauhan", "WR-MED-2020", DepartmentChoices.MEDICAL, MemberStatus.ACTIVE, "Chief Pharmacist, Jagjivan Ram Hospital", [("Nisha Chauhan", "SPOUSE", 45)]),

            # 21 to 30: Active
            ("Vinayak Dattatray Kadam", "CR-ENG-2121", DepartmentChoices.ENGINEERING, MemberStatus.ACTIVE, "Bridge Inspector, Kalyan Division", [("Savita Kadam", "SPOUSE", 48)]),
            ("Shabana Parveen Shaikh", "CR-COM-2222", DepartmentChoices.COMMERCIAL, MemberStatus.ACTIVE, "Chief Ticket Examiner, LTT Terminus", [("Jameel Shaikh", "SPOUSE", 49), ("Zoya Shaikh", "DAUGHTER", 17)]),
            ("Gopal Krishna Murthy", "SR-ACC-2323", DepartmentChoices.ACCOUNTS, MemberStatus.ACTIVE, "Senior Auditor, Western Railway Accounts", [("Janaki Murthy", "SPOUSE", 54)]),
            ("Brijesh Ramshankar Shukla", "NER-OPS-2424", DepartmentChoices.OPERATING, MemberStatus.ACTIVE, "Traffic Controller, CSMT Control Room", [("Gayatri Shukla", "SPOUSE", 46)]),
            ("Prashant Arvind Sawant", "CR-MEC-2525", DepartmentChoices.MECHANICAL, MemberStatus.ACTIVE, "Boiler Maker, Kurla Diesel Shed", [("Pallavi Sawant", "SPOUSE", 39)]),
            ("Mahesh Ramchandra More", "WR-ELE-2626", DepartmentChoices.ELECTRICAL, MemberStatus.ACTIVE, "Electrical Fitter Grade I, Mahalaxmi", [("Vandana More", "SPOUSE", 42)]),
            ("Pravin Kisan Kamble", "CR-SNT-2727", DepartmentChoices.SIGNAL_TELECOM, MemberStatus.ACTIVE, "Signal Maintainer, Sandhurst Road", [("Ranjana Kamble", "SPOUSE", 36)]),
            ("Naveen Surendra Chawla", "NR-STO-2828", DepartmentChoices.STORES, MemberStatus.ACTIVE, "Assistant Material Manager, Lower Parel", [("Monika Chawla", "SPOUSE", 43)]),
            ("Umesh Narhari Bhat", "SWR-PER-2929", DepartmentChoices.PERSONNEL, MemberStatus.ACTIVE, "Senior Clerk (Establishment), Churchgate", [("Vidya Bhat", "SPOUSE", 47)]),
            ("Satish Govind Parab", "KR-ENG-3030", DepartmentChoices.ENGINEERING, MemberStatus.ACTIVE, "Junior Engineer (Works), Vashi", [("Shraddha Parab", "SPOUSE", 35)]),

            # 31 to 40: Due (Some partially paid, some in grace)
            ("Devendra Singh Rathore", "NWR-OPS-3131", DepartmentChoices.OPERATING, MemberStatus.DUE, "Station Superintendent, Andheri. Renewal fee pending.", [("Urmila Rathore", "SPOUSE", 50)]),
            ("Kishore Nanaji Wankhede", "CR-ELE-3232", DepartmentChoices.ELECTRICAL, MemberStatus.DUE, "Overhead Equipment (OHE) Inspector, Igatpuri", [("Chhaya Wankhede", "SPOUSE", 45)]),
            ("Balram Radheshyam Yadav", "NER-ENG-3333", DepartmentChoices.ENGINEERING, MemberStatus.DUE, "Gangman / Trackman Unit 4, Kasara", [("Kamala Yadav", "SPOUSE", 38)]),
            ("Anjali Vinod Deshpande", "CR-ACC-3434", DepartmentChoices.ACCOUNTS, MemberStatus.DUE, "Section Officer (Finance), Mumbai CSMT", [("Vinod Deshpande", "SPOUSE", 49)]),
            ("Jagdish Chandra Bhatt", "WR-MEC-3535", DepartmentChoices.MECHANICAL, MemberStatus.DUE, "Loco Pilot Passenger, Bandra Terminus", [("Pushpa Bhatt", "SPOUSE", 48)]),
            ("Rupesh Shantaram Rane", "KR-RPF-3636", DepartmentChoices.SECURITY_RPF, MemberStatus.DUE, "Head Constable, RPF Crime Intelligence Branch", [("Snehal Rane", "SPOUSE", 39)]),
            ("Siddharth Gautam Mane", "CR-COM-3737", DepartmentChoices.COMMERCIAL, MemberStatus.DUE, "Parcel Clerk, Dadar Goods Depot", [("Poonam Mane", "SPOUSE", 34)]),
            ("Hemant Vithal Chaudhari", "WR-SNT-3838", DepartmentChoices.SIGNAL_TELECOM, MemberStatus.DUE, "Microwave Telecom Technician, Malad", [("Jyoti Chaudhari", "SPOUSE", 41)]),
            ("Gajanan Laxman Tambe", "CR-STO-3939", DepartmentChoices.STORES, MemberStatus.DUE, "Stores Depot Ward In-Charge, Kurla", [("Shubhangi Tambe", "SPOUSE", 46)]),
            ("Chandrakant Babu Nalawade", "WR-PER-4040", DepartmentChoices.PERSONNEL, MemberStatus.DUE, "Staff Benefit Fund Secretary, Divisional HQ", [("Sulabha Nalawade", "SPOUSE", 53)]),

            # 41 to 45: Expired (Past validity and grace period)
            ("Nandkishor Bapu Mhaske", "CR-ENG-4141", DepartmentChoices.ENGINEERING, MemberStatus.EXPIRED, "Retired SSE Works. Membership expired past grace.", []),
            ("Rajendra Prasad Gupta", "ECR-OPS-4242", DepartmentChoices.OPERATING, MemberStatus.EXPIRED, "Ex-Station Master. Transferred out of division.", []),
            ("Sulekha Anantrao Kulkarni", "WR-MED-4343", DepartmentChoices.MEDICAL, MemberStatus.EXPIRED, "Senior Nursing Officer. Plan expired.", []),
            ("Gopal Balkrishna Joshi", "CR-ACC-4444", DepartmentChoices.ACCOUNTS, MemberStatus.EXPIRED, "Accounts Assistant. Lapsed subscription.", []),
            ("Surendra Kumar Paswan", "ER-MEC-4545", DepartmentChoices.MECHANICAL, MemberStatus.EXPIRED, "Fitter Grade II. Membership lapsed.", []),

            # 46 to 48: Removed (Soft-deleted)
            ("Ashwini Mohan Deshmukh", "WR-COM-4646", DepartmentChoices.COMMERCIAL, MemberStatus.REMOVED, "Transferred to South Western Railway Hubballi division.", []),
            ("Prashant Madhukar Joshi", "CR-ENG-4747", DepartmentChoices.ENGINEERING, MemberStatus.REMOVED, "Resigned from Indian Railways service.", []),
            ("Vijay Pandurang Ghadge", "WR-RPF-4848", DepartmentChoices.SECURITY_RPF, MemberStatus.REMOVED, "Transferred to Central Vigilance Organisation, New Delhi.", []),

            # 49 to 50: Suspended
            ("Ajay Vikramaditya Somani", "WR-STO-4949", DepartmentChoices.STORES, MemberStatus.SUSPENDED, "Membership suspended pending administrative inquiry.", []),
            ("Pratibha Digambar Bhosale", "CR-PER-5050", DepartmentChoices.PERSONNEL, MemberStatus.SUSPENDED, "Temporarily suspended by Institute Executive Committee resolution.", []),
        ]

        today = timezone.now().date()
        created_count = 0
        payment_count = 0
        family_count = 0
        renewal_count = 0

        self.stdout.write(f"Seeding {len(raw_members_data)} realistic railway members...")

        with transaction.atomic():
            for idx, item in enumerate(raw_members_data, start=1):
                name, emp_id, dept, status, notes, family_list = item
                phone = f"+91987654{idx:04d}"
                bindex = compute_blind_index(phone)

                member, created = Member.objects.get_or_create(
                    phone_blind_index=bindex,
                    defaults={
                        'name': name,
                        'phone': phone,
                        'employee_id': emp_id,
                        'department': dept,
                        'status': status,
                        'address': f"Flat {100 + idx}, Railway Colony, Quarter Area, Mumbai",
                        'date_joined': date(2024, 1, 1),
                        'notes': notes,
                        'is_removed': (status == MemberStatus.REMOVED),
                        'removed_at': timezone.now() if status == MemberStatus.REMOVED else None,
                        'removal_reason': notes if status == MemberStatus.REMOVED else '',
                        'removed_by': admin_user if status == MemberStatus.REMOVED else None,
                    }
                )
                if created:
                    created_count += 1

                # Plan Assignment setup
                if status in [MemberStatus.ACTIVE, MemberStatus.DUE]:
                    # Determine start and end dates
                    if status == MemberStatus.ACTIVE:
                        # Active: started 2026-01-01, ends 2026-12-31
                        start_date = date(2026, 1, 1)
                        chosen_plan = annual_plan if idx % 3 != 0 else half_yearly_plan
                        end_date = chosen_plan.compute_end_date(start_date)
                        discount = senior_concession if idx % 5 == 0 else None
                    else:
                        # Due: some near expiry, some recently renewed
                        if idx % 2 == 0:
                            start_date = today - timedelta(days=350)
                            chosen_plan = annual_plan
                            end_date = start_date + timedelta(days=364)  # expiring in ~15 days
                        else:
                            start_date = today
                            chosen_plan = quarterly_plan
                            end_date = chosen_plan.compute_end_date(start_date)
                        discount = None

                    assignment, a_created = MemberPlanAssignment.objects.get_or_create(
                        member=member,
                        is_current=True,
                        defaults={
                            'plan': chosen_plan,
                            'discount': discount,
                            'start_date': start_date,
                            'end_date': end_date,
                            'grace_period_days': chosen_plan.grace_period_days,
                            'base_fee': chosen_plan.fee,
                            'assigned_by': admin_user,
                        }
                    )

                    # Payments
                    if status == MemberStatus.ACTIVE and not member.payments.exists():
                        # Fully paid
                        p_mode = [PaymentMode.UPI, PaymentMode.BANK_TRANSFER, PaymentMode.CASH][idx % 3]
                        ref = f"UTR-{20260000 + idx}" if p_mode != PaymentMode.CASH else ""
                        Payment.objects.create(
                            member=member,
                            plan_assignment=assignment,
                            amount=assignment.final_fee,
                            payment_date=start_date,
                            payment_mode=p_mode,
                            reference_number=ref,
                            collected_by=acct_user,
                            status=PaymentStatus.COMPLETED
                        )
                        payment_count += 1

                    elif status == MemberStatus.DUE and not member.payments.exists():
                        # Partial payment or unpaid
                        if idx % 2 == 0:
                            partial_amt = Decimal('500.00')
                            Payment.objects.create(
                                member=member,
                                plan_assignment=assignment,
                                amount=partial_amt,
                                payment_date=start_date,
                                payment_mode=PaymentMode.UPI,
                                reference_number=f"PARTIAL-{20260000 + idx}",
                                collected_by=acct_user,
                                status=PaymentStatus.COMPLETED
                            )
                            payment_count += 1

                elif status == MemberStatus.EXPIRED:
                    # Expired: validity ended in 2025
                    start_date = date(2025, 1, 1)
                    end_date = date(2025, 12, 31)
                    MemberPlanAssignment.objects.get_or_create(
                        member=member,
                        is_current=True,
                        defaults={
                            'plan': annual_plan,
                            'start_date': start_date,
                            'end_date': end_date,
                            'grace_period_days': 15,
                            'base_fee': annual_plan.fee,
                            'assigned_by': admin_user,
                        }
                    )

                # Family dependents
                for fam_name, rel, age in family_list:
                    dob = today - timedelta(days=age * 365)
                    MemberFamily.objects.get_or_create(
                        member=member,
                        name=fam_name,
                        defaults={
                            'relationship': rel,
                            'date_of_birth': dob,
                        }
                    )
                    family_count += 1

                # Historical renewals for members 1 to 10
                if idx <= 10 and not member.renewal_records.exists():
                    prev_assignment = MemberPlanAssignment.objects.create(
                        member=member,
                        plan=annual_plan,
                        start_date=date(2025, 1, 1),
                        end_date=date(2025, 12, 31),
                        base_fee=annual_plan.fee,
                        is_current=False,
                        assigned_by=admin_user,
                        notes="Initial 2025 subscription cycle"
                    )
                    curr_assignment = member.plan_assignments.filter(is_current=True).first()
                    if curr_assignment:
                        RenewalRecord.objects.create(
                            member=member,
                            previous_assignment=prev_assignment,
                            new_assignment=curr_assignment,
                            plan=curr_assignment.plan,
                            renewed_by=acct_user,
                            previous_end_date=prev_assignment.end_date,
                            new_start_date=curr_assignment.start_date,
                            new_end_date=curr_assignment.end_date,
                            fee_charged=curr_assignment.final_fee,
                            notes="Renewed by Accountant via Portal"
                        )
                        renewal_count += 1

        total_members = Member.objects.count()
        active_count = Member.objects.filter(status=MemberStatus.ACTIVE, is_removed=False).count()
        due_count = Member.objects.filter(status=MemberStatus.DUE, is_removed=False).count()
        expired_count = Member.objects.filter(status=MemberStatus.EXPIRED, is_removed=False).count()
        removed_count = Member.objects.filter(is_removed=True).count()

        self.stdout.write(
            self.style.SUCCESS(
                f"\nPhase 1 Database Hardening & 50-Member Seed Complete:\n"
                f"  Total Members in Database: {total_members}\n"
                f"  - Active: {active_count}\n"
                f"  - Due / Grace: {due_count}\n"
                f"  - Expired: {expired_count}\n"
                f"  - Removed (Soft-Deleted): {removed_count}\n"
                f"  Total Family Dependents Seeded: {MemberFamily.objects.count()}\n"
                f"  Total Payments Recorded: {Payment.objects.count()}\n"
                f"  Total Renewal Rollover Logs: {RenewalRecord.objects.count()}"
            )
        )
