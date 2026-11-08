from django.apps import AppConfig


class PrintingConfig(AppConfig):
    name = 'printing'

    def ready(self):
        from . import signals  # noqa: F401  (registers signal handlers)
        from . import api_docs, printer_api  # noqa: F401  (register the OpenAPI auth schemes)
