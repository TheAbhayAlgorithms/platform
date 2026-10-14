from django.core.management.base import BaseCommand
from transfers.models import Branch


class Command(BaseCommand):
    help = "Seeds initial Indian Railways divisions and club branches."

    def handle(self, *args, **options):
        initial_branches = [
            {
                'name': "Delhi Main Railway Employees' Club",
                'code': "NR-DLI",
                'zone': "Northern Railway",
                'division': "Delhi",
                'city': "New Delhi",
                'state': "Delhi",
                'contact_person': "Sr. Divisional Personnel Officer",
                'contact_phone': "+91 11 2334 0001",
                'contact_email': "dli.institute@railclub.in",
                'is_home_branch': True,
                'is_active': True,
            },
            {
                'name': "Mumbai Central Railway Institute",
                'code': "WR-MMCT",
                'zone': "Western Railway",
                'division': "Mumbai",
                'city': "Mumbai",
                'state': "Maharashtra",
                'contact_person': "Honorary Secretary",
                'contact_phone': "+91 22 2307 1234",
                'contact_email': "mmct.institute@railclub.in",
                'is_home_branch': False,
                'is_active': True,
            },
            {
                'name': "Howrah Railway Officers & Staff Club",
                'code': "ER-HWH",
                'zone': "Eastern Railway",
                'division': "Howrah",
                'city': "Kolkata",
                'state': "West Bengal",
                'contact_person': "Divisional Railway Manager Office",
                'contact_phone': "+91 33 2660 5678",
                'contact_email': "hwh.club@railclub.in",
                'is_home_branch': False,
                'is_active': True,
            },
            {
                'name': "Secunderabad Railway Institute",
                'code': "SCR-SC",
                'zone': "South Central Railway",
                'division': "Secunderabad",
                'city': "Secunderabad",
                'state': "Telangana",
                'contact_person': "Institute Secretary",
                'contact_phone': "+91 40 2782 4321",
                'contact_email': "sc.institute@railclub.in",
                'is_home_branch': False,
                'is_active': True,
            },
            {
                'name': "Chennai Central Railway Employees' Club",
                'code': "SR-MAS",
                'zone': "Southern Railway",
                'division': "Chennai",
                'city': "Chennai",
                'state': "Tamil Nadu",
                'contact_person': "Welfare Officer",
                'contact_phone': "+91 44 2535 9876",
                'contact_email': "mas.club@railclub.in",
                'is_home_branch': False,
                'is_active': True,
            },
            {
                'name': "Danapur Divisional Railway Institute",
                'code': "ECR-DNR",
                'zone': "East Central Railway",
                'division': "Danapur",
                'city': "Patna",
                'state': "Bihar",
                'contact_person': "Sr. DPO Secretariat",
                'contact_phone': "+91 6115 222100",
                'contact_email': "dnr.institute@railclub.in",
                'is_home_branch': False,
                'is_active': True,
            },
        ]

        created_count = 0
        for data in initial_branches:
            branch, created = Branch.objects.update_or_create(
                code=data['code'],
                defaults=data
            )
            if created:
                created_count += 1

        self.stdout.write(
            self.style.SUCCESS(f"Successfully processed {len(initial_branches)} branches ({created_count} created).")
        )
