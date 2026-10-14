from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from accounts.models import UserProfile, RoleChoices

class Command(BaseCommand):
    help = "Seeds demo administrative users with different roles for RailClub Connect."

    def handle(self, *args, **options):
        demo_users = [
            {
                'username': 'superadmin',
                'email': 'superadmin@railclub.fake',
                'first_name': 'Rajesh',
                'last_name': 'Kumar',
                'password': 'Admin@RailClub2026!',
                'role': RoleChoices.SUPER_ADMIN,
                'phone': '+919876543210',
            },
            {
                'username': 'accountant',
                'email': 'accountant@railclub.fake',
                'first_name': 'Sunita',
                'last_name': 'Sharma',
                'password': 'Acct@RailClub2026!',
                'role': RoleChoices.ACCOUNTANT,
                'phone': '+919876543211',
            },
            {
                'username': 'eventmanager',
                'email': 'events@railclub.fake',
                'first_name': 'Vikram',
                'last_name': 'Singh',
                'password': 'Event@RailClub2026!',
                'role': RoleChoices.EVENT_MANAGER,
                'phone': '+919876543212',
            },
            {
                'username': 'viewer',
                'email': 'viewer@railclub.fake',
                'first_name': 'Ananya',
                'last_name': 'Patel',
                'password': 'View@RailClub2026!',
                'role': RoleChoices.VIEWER,
                'phone': '+919876543213',
            },
        ]

        for item in demo_users:
            user, created = User.objects.get_or_create(username=item['username'])
            user.email = item['email']
            user.first_name = item['first_name']
            user.last_name = item['last_name']
            user.set_password(item['password'])
            user.is_staff = True
            user.is_superuser = (item['role'] == RoleChoices.SUPER_ADMIN)
            user.save()

            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = item['role']
            profile.phone = item['phone']
            profile.is_2fa_enabled = True
            profile.failed_login_attempts = 0
            profile.locked_until = None
            profile.save()

            action_str = "Created" if created else "Updated"
            self.stdout.write(
                self.style.SUCCESS(
                    f"{action_str} {item['role']}: {item['username']} / {item['password']} (2FA: {item['phone']})"
                )
            )

        self.stdout.write(self.style.SUCCESS("Successfully seeded Module 1 demo accounts!"))
