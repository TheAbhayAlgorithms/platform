from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from members.models import Member, MemberFamily, MemberStatus, DepartmentChoices

class Command(BaseCommand):
    help = "Seeds demo railway employee members with diverse statuses and dependent family records."

    def handle(self, *args, **options):
        demo_members = [
            {
                'name': 'Ramesh Chandra Verma',
                'phone': '+919876500001',
                'employee_id': 'WR-ENG-2041',
                'department': DepartmentChoices.ENGINEERING,
                'address': 'Flat 102, Railway Officers Colony, Bandra East, Mumbai',
                'date_joined': date(2023, 1, 15),
                'status': MemberStatus.ACTIVE,
                'whatsapp_opt_in': True,
                'notes': 'Senior Section Engineer (P-Way). Regular institute attendee.',
                'family': [
                    {'name': 'Shanti Verma', 'relationship': 'SPOUSE', 'dob': date(1982, 4, 10)},
                    {'name': 'Aditya Verma', 'relationship': 'SON', 'dob': date(2010, 8, 22)},
                ]
            },
            {
                'name': 'Pooja Kulkarni',
                'phone': '+919876500002',
                'employee_id': 'CR-COM-4109',
                'department': DepartmentChoices.COMMERCIAL,
                'address': 'Quarter B-4, Central Railway Colony, Matunga, Mumbai',
                'date_joined': date(2023, 6, 1),
                'status': MemberStatus.ACTIVE,
                'whatsapp_opt_in': True,
                'notes': 'Commercial Inspector, CSMT division.',
                'family': [
                    {'name': 'Makarand Kulkarni', 'relationship': 'SPOUSE', 'dob': date(1985, 11, 3)},
                    {'name': 'Ananya Kulkarni', 'relationship': 'DAUGHTER', 'dob': date(2014, 2, 18)},
                ]
            },
            {
                'name': 'Devendra Singh Rathore',
                'phone': '+919876500003',
                'employee_id': 'WR-OPS-1198',
                'department': DepartmentChoices.OPERATING,
                'address': 'Station Quarter 5, Dadar Western, Mumbai',
                'date_joined': date(2024, 2, 10),
                'status': MemberStatus.DUE,
                'whatsapp_opt_in': True,
                'notes': 'Station Master, Dadar. Outstanding quarterly fee.',
                'family': [
                    {'name': 'Urmila Rathore', 'relationship': 'SPOUSE', 'dob': date(1979, 7, 25)},
                ]
            },
            {
                'name': 'Mohammed Farooq Khan',
                'phone': '+919876500004',
                'employee_id': 'WR-MEC-8831',
                'department': DepartmentChoices.MECHANICAL,
                'address': 'Block 12, Parel Loco Workshop Colony, Mumbai',
                'date_joined': date(2022, 4, 1),
                'status': MemberStatus.EXPIRED,
                'whatsapp_opt_in': True,
                'notes': 'Loco Pilot (Mail/Express). Membership lapsed in previous cycle.',
                'family': [
                    {'name': 'Zainab Khan', 'relationship': 'SPOUSE', 'dob': date(1988, 1, 14)},
                    {'name': 'Ibrahim Khan', 'relationship': 'SON', 'dob': date(2016, 9, 5)},
                    {'name': 'Aisha Khan', 'relationship': 'DAUGHTER', 'dob': date(2019, 12, 30)},
                ]
            },
            {
                'name': 'Kavita Sundaram',
                'phone': '+919876500005',
                'employee_id': 'CR-ACC-3342',
                'department': DepartmentChoices.ACCOUNTS,
                'address': 'Flat 304, New Railway Colony, Kurla East, Mumbai',
                'date_joined': date(2023, 9, 20),
                'status': MemberStatus.ACTIVE,
                'whatsapp_opt_in': True,
                'notes': 'Senior Accounts Officer. Institute festival planning committee member.',
                'family': []
            },
            {
                'name': 'Balwinder Singh Gill',
                'phone': '+919876500006',
                'employee_id': 'WR-RPF-5590',
                'department': DepartmentChoices.SECURITY_RPF,
                'address': 'Barrack Line Qtr 8, RPF Lines, Mumbai Central',
                'date_joined': date(2023, 11, 1),
                'status': MemberStatus.SUSPENDED,
                'whatsapp_opt_in': False,
                'notes': 'Inspector RPF. Membership temporarily suspended upon transfer enquiry.',
                'family': [
                    {'name': 'Harpreet Kaur Gill', 'relationship': 'SPOUSE', 'dob': date(1983, 5, 12)},
                ]
            },
            {
                'name': 'Sanjay Babanrao Jadhav',
                'phone': '+919876500007',
                'employee_id': 'CR-SNT-7721',
                'department': DepartmentChoices.SIGNAL_TELECOM,
                'address': 'Railway Quarter 22, Kalyan West, Thane',
                'date_joined': date(2024, 1, 10),
                'status': MemberStatus.ACTIVE,
                'whatsapp_opt_in': True,
                'notes': 'Junior Engineer (Signals).',
                'family': [
                    {'name': 'Lata Jadhav', 'relationship': 'SPOUSE', 'dob': date(1990, 3, 21)},
                ]
            },
        ]

        count = 0
        for item in demo_members:
            from core.encryption import compute_blind_index
            blind_idx = compute_blind_index(item['phone'])
            member = Member.objects.filter(phone_blind_index=blind_idx).first()

            if not member:
                member = Member.objects.create(
                    name=item['name'],
                    phone=item['phone'],
                    employee_id=item['employee_id'],
                    department=item['department'],
                    address=item['address'],
                    date_joined=item['date_joined'],
                    status=item['status'],
                    whatsapp_opt_in=item['whatsapp_opt_in'],
                    notes=item['notes'],
                )
                action = "Created"
                count += 1
            else:
                member.name = item['name']
                member.employee_id = item['employee_id']
                member.department = item['department']
                member.address = item['address']
                member.status = item['status']
                member.whatsapp_opt_in = item['whatsapp_opt_in']
                member.notes = item['notes']
                member.save()
                action = "Updated"

            # Create family dependents if missing
            for fam in item['family']:
                MemberFamily.objects.get_or_create(
                    member=member,
                    name=fam['name'],
                    defaults={
                        'relationship': fam['relationship'],
                        'date_of_birth': fam['dob'],
                    }
                )

            self.stdout.write(
                self.style.SUCCESS(
                    f"{action} Member {member.membership_id}: {member.name} ({member.get_status_display()}) - {member.phone}"
                )
            )

        self.stdout.write(self.style.SUCCESS(f"Successfully seeded {count} demo member records!"))
