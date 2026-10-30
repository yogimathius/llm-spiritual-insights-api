"""Delete conversation history and deliberation runs older than the retention period."""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ai_app.models.deliberation import DeliberationRun
from ai_app.models.history import History


class Command(BaseCommand):
    help = "Prune history and deliberation runs older than DATA_RETENTION_DAYS"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report counts without deleting")

    def handle(self, *args, **options):
        retention_days = settings.DATA_RETENTION_DAYS
        if retention_days <= 0:
            raise CommandError("DATA_RETENTION_DAYS must be a positive integer.")

        cutoff = timezone.now() - timedelta(days=retention_days)
        old_history = History.objects.filter(created_at__lt=cutoff)
        old_runs = DeliberationRun.objects.filter(created_at__lt=cutoff)
        history_count = old_history.count()
        run_count = old_runs.count()

        if options["dry_run"]:
            self.stdout.write(
                f"Would delete {history_count} history records and {run_count} deliberation runs "
                f"older than {cutoff.isoformat()}."
            )
            return

        old_history.delete()
        old_runs.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {history_count} history records and {run_count} deliberation runs "
                f"older than {cutoff.isoformat()}."
            )
        )
