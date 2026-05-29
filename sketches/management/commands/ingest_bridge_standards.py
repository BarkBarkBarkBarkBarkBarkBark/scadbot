from django.core.management.base import BaseCommand, CommandError

from sketches.pipeline.standards_ingest import StandardIngestor


class Command(BaseCommand):
    help = "Fetch CalTrans bridge standards PDFs, extract text, chunk them, and optionally embed them."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None, help="Limit number of discovered PDFs")
        parser.add_argument("--refresh", action="store_true", help="Reprocess standards even if already chunked")
        parser.add_argument("--skip-embeddings", action="store_true", help="Do not request embeddings")

    def handle(self, *args, **options):
        try:
            ingestor = StandardIngestor()
            stats = ingestor.ingest(
                limit=options["limit"],
                refresh=options["refresh"],
                with_embeddings=not options["skip_embeddings"],
            )
        except Exception as exc:  # noqa: BLE001
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("standards ingestion complete"))
        for key, value in stats.items():
            self.stdout.write(f"  {key}: {value}")
