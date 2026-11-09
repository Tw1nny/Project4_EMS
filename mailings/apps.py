from django.apps import AppConfig


class MailingsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mailings"
    verbose_name = "Рассылки"

    def ready(self):
        # Сигналы сбрасывают кеш при изменении данных.
        import mailings.signals  # noqa: F401
