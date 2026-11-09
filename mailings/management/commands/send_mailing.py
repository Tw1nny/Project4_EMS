"""
Ручной запуск рассылки из командной строки.

    python manage.py send_mailing 5          # отправить рассылку №5
    python manage.py send_mailing --all      # все рассылки, которые сейчас можно отправить
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from mailings.models import Mailing, MailingAttempt
from mailings.services import MailingSendError, send_mailing


class Command(BaseCommand):
    help = "Отправляет рассылку по её номеру или все активные рассылки (--all)"

    def add_arguments(self, parser):
        parser.add_argument("mailing_id", nargs="?", type=int, help="Номер рассылки")
        parser.add_argument("--all", action="store_true", help="Отправить все рассылки в статусе «Запущена»")

    def handle(self, *args, mailing_id=None, **options):
        if options["all"]:
            now = timezone.now()
            mailings = Mailing.objects.filter(start_time__lte=now, end_time__gte=now, is_active=True)
            if not mailings.exists():
                self.stdout.write("Сейчас нет рассылок, которые можно отправить.")
                return
            for mailing in mailings:
                self.send(mailing)
            return

        if mailing_id is None:
            raise CommandError("Укажите номер рассылки или --all.")

        try:
            mailing = Mailing.objects.select_related("message").get(pk=mailing_id)
        except Mailing.DoesNotExist:
            raise CommandError(f"Рассылка №{mailing_id} не найдена.")
        self.send(mailing)

    def send(self, mailing):
        try:
            attempts = send_mailing(mailing)
        except MailingSendError as exc:
            self.stdout.write(self.style.ERROR(f"{mailing}: {exc}"))
            return
        success = sum(1 for a in attempts if a.status == MailingAttempt.Status.SUCCESS)
        failure = len(attempts) - success
        self.stdout.write(self.style.SUCCESS(f"{mailing}: успешно — {success}, с ошибкой — {failure}."))
