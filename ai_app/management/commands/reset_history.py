from django.core.management.base import BaseCommand

from ai_app.models.history import History


class Command(BaseCommand):
    help = "Resets the history table to prepare for new array-based responses"

    def handle(self, *args, **options):
        # Delete all history records
        History.objects.all().delete()
        self.stdout.write(self.style.SUCCESS("Successfully reset history table"))
