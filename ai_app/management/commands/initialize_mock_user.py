from django.core.management.base import BaseCommand

from ai_app.models.user import User


class Command(BaseCommand):
    help = "Idempotently initialize local test user"

    def handle(self, *args, **kwargs):
        user, created = User.objects.get_or_create(
            username="testuser",
            defaults={"email": "testuser@local.perspective-loom.internal"},
        )
        status_msg = "Created" if created else "Verified existing"
        self.stdout.write(self.style.SUCCESS(f"{status_msg} user '{user.username}'"))
