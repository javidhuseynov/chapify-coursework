from django.conf import settings
from django.core.management.base import BaseCommand

from printing import api_tokens, services


class Command(BaseCommand):
    help = (
        "Retention policy (NFR-10): expire unpaid requests and delete uploaded "
        "files that are no longer needed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=settings.DOCUMENT_RETENTION_HOURS,
            help=f"Age limit in hours (default {settings.DOCUMENT_RETENTION_HOURS}).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Only report what would be done.")

    def handle(self, *args, **options):
        summary = services.cleanup_documents(older_than_hours=options["hours"], dry_run=options["dry_run"])
        prefix = "[dry run] " if options["dry_run"] else ""
        self.stdout.write(
            f"{prefix}Expired unpaid requests: {summary['expired_requests']}, "
            f"abandoned uploads deleted: {summary['orphan_files']}, "
            f"leftover files of finished requests deleted: {summary['terminal_files']}."
        )

        if not options["dry_run"]:
            purged = api_tokens.purge_old_tokens()
            self.stdout.write(f"Old expired or revoked API tokens deleted: {purged}.")
