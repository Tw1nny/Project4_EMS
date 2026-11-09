"""
Модели сервиса рассылок.

- Recipient — получатель рассылки (клиент).
- Message — сообщение (тема и тело письма).
- Mailing — рассылка: период отправки, статус, сообщение, получатели.
  Статус вычисляется по текущему времени методом update_status().
- MailingAttempt — попытка отправки письма одному получателю.

У клиентов, сообщений и рассылок есть владелец (owner): пользователь
видит и меняет только свои данные, менеджер видит всё.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class Recipient(models.Model):
    email = models.EmailField(unique=True, verbose_name="Email")
    full_name = models.CharField(max_length=255, verbose_name="Ф. И. О.")
    comment = models.TextField(blank=True, verbose_name="Комментарий")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recipients",
        verbose_name="Владелец",
    )

    class Meta:
        verbose_name = "Получатель рассылки"
        verbose_name_plural = "Получатели рассылки"
        ordering = ["full_name"]
        permissions = [
            ("can_view_all_recipients", "Может просматривать всех получателей"),
        ]

    def __str__(self):
        return f"{self.full_name} <{self.email}>"


class Message(models.Model):
    subject = models.CharField(max_length=255, verbose_name="Тема письма")
    body = models.TextField(verbose_name="Тело письма")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mail_messages",
        verbose_name="Владелец",
    )

    class Meta:
        verbose_name = "Сообщение"
        verbose_name_plural = "Сообщения"
        ordering = ["subject"]
        permissions = [
            ("can_view_all_messages", "Может просматривать все сообщения"),
        ]

    def __str__(self):
        return self.subject


class Mailing(models.Model):
    class Status(models.TextChoices):
        CREATED = "Создана", "Создана"
        STARTED = "Запущена", "Запущена"
        FINISHED = "Завершена", "Завершена"

    start_time = models.DateTimeField(verbose_name="Дата и время начала отправки")
    end_time = models.DateTimeField(verbose_name="Дата и время окончания отправки")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CREATED,
        verbose_name="Статус",
    )
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="mailings",
        verbose_name="Сообщение",
    )
    recipients = models.ManyToManyField(Recipient, related_name="mailings", verbose_name="Получатели")
    is_active = models.BooleanField(
        default=True,
        verbose_name="Активна",
        help_text="Менеджер может отключить рассылку — тогда её нельзя отправить.",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mailings",
        verbose_name="Владелец",
    )

    class Meta:
        verbose_name = "Рассылка"
        verbose_name_plural = "Рассылки"
        ordering = ["-start_time"]
        permissions = [
            ("can_view_all_mailings", "Может просматривать все рассылки"),
            ("can_disable_mailing", "Может отключать рассылки"),
        ]

    def __str__(self):
        return f"Рассылка №{self.pk}: {self.message}"

    def calculate_status(self, now=None):
        now = now or timezone.now()
        if now < self.start_time:
            return self.Status.CREATED
        if now <= self.end_time:
            return self.Status.STARTED
        return self.Status.FINISHED

    def update_status(self):
        """Пересчитывает статус по текущему времени и сохраняет, если он изменился."""
        new_status = self.calculate_status()
        if new_status != self.status:
            self.status = new_status
            self.save(update_fields=["status"])
        return self.status

    @classmethod
    def refresh_statuses(cls):
        """Обновляет статусы всех рассылок тремя запросами. Возвращает число изменённых."""
        now = timezone.now()
        updated = cls.objects.filter(start_time__gt=now).exclude(status=cls.Status.CREATED).update(
            status=cls.Status.CREATED
        )
        updated += (
            cls.objects.filter(start_time__lte=now, end_time__gte=now)
            .exclude(status=cls.Status.STARTED)
            .update(status=cls.Status.STARTED)
        )
        updated += cls.objects.filter(end_time__lt=now).exclude(status=cls.Status.FINISHED).update(
            status=cls.Status.FINISHED
        )
        return updated

    def can_be_sent_now(self, now=None):
        now = now or timezone.now()
        return self.is_active and self.start_time <= now <= self.end_time


class MailingAttempt(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "Успешно", "Успешно"
        FAILURE = "Не успешно", "Не успешно"

    attempt_time = models.DateTimeField(default=timezone.now, verbose_name="Дата и время попытки")
    status = models.CharField(max_length=20, choices=Status.choices, verbose_name="Статус")
    server_response = models.TextField(blank=True, verbose_name="Ответ почтового сервера")
    mailing = models.ForeignKey(
        Mailing,
        on_delete=models.CASCADE,
        related_name="attempts",
        verbose_name="Рассылка",
    )
    recipient = models.ForeignKey(
        Recipient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attempts",
        verbose_name="Получатель",
    )

    class Meta:
        verbose_name = "Попытка рассылки"
        verbose_name_plural = "Попытки рассылки"
        ordering = ["-attempt_time"]

    def __str__(self):
        return f"{self.attempt_time:%d.%m.%Y %H:%M} — {self.status}"
