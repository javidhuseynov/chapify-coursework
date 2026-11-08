from django.apps import AppConfig


class PrintingConfig(AppConfig):
    name = 'printing'

    def ready(self):
        from . import signals  # noqa: F401  (registers signal handlers)
        from . import api_docs  # noqa: F401  (registers the OpenAPI token scheme)
