"""Create (or delete) accounts for load testing: loadtest_001, loadtest_002, ...

Only for a local test database. The accounts are ordinary students.
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

PREFIX = "loadtest_"


class Command(BaseCommand):
    help = "Create N student accounts for load testing (loadtest_001 ...), or delete them with --delete."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=50)
        parser.add_argument("--password", default="Load-test-pass-2026")
        parser.add_argument("--delete", action="store_true", help="Delete all loadtest_ accounts and their data.")

    def handle(self, *args, **options):
        if options["delete"]:
            deleted, _ = User.objects.filter(username__startswith=PREFIX).delete()
            self.stdout.write(f"Deleted {deleted} load-test records.")
            return

        created = 0
        for number in range(1, options["count"] + 1):
            username = f"{PREFIX}{number:03d}"
            if not User.objects.filter(username=username).exists():
                User.objects.create_user(username, f"{username}@example.com", options["password"])
                created += 1
        self.stdout.write(
            f"{created} new load-test account(s); {options['count']} available "
            f"({PREFIX}001 ... {PREFIX}{options['count']:03d})."
        )
