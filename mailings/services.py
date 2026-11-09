"""
Сервисный слой: отправка рассылок, статистика и кеширование.

Отправка (send_mailing):
1. Проверка: рассылка не отключена и текущее время между start_time
   и end_time. Иначе — MailingSendError с понятным текстом.
2. Получатели — все клиенты, связанные с рассылкой.
3. Каждому send_mail(); результат — попытка «Успешно» или «Не успешно»
   с текстом ошибки. Попытки сохраняются одним запросом (bulk_create).

Кеш (Redis):
- данные хранятся под ключами с «версией» раздела, например
  recipients_v3_user_5. Когда данные раздела меняются, сигналы
  (mailings/signals.py) увеличивают версию, и старые записи больше не
  используются — пользователь сразу видит изменения;
- показатели главной страницы кешируются под ключом home_stats.
"""

import smtplib

from django.conf import settings
from django.core.cache import cache
from django.core.mail import BadHeaderError, send_mail
from django.db.models import Count, Q
from django.utils import timezone

from mailings.models import Mailing, MailingAttempt, Message, Recipient

HOME_STATS_KEY = "home_stats"


class MailingSendError(Exception):
    """Рассылку сейчас отправить нельзя."""


# --- Отправка ---

def send_mailing(mailing):
    """Отправляет рассылку всем её получателям. Возвращает список попыток."""
    mailing.update_status()

    if not mailing.is_active:
        raise MailingSendError("Рассылка отключена менеджером — отправить её нельзя.")

    now = timezone.now()
    if not mailing.can_be_sent_now(now):
        start = timezone.localtime(mailing.start_time).strftime("%d.%m.%Y %H:%M")
        end = timezone.localtime(mailing.end_time).strftime("%d.%m.%Y %H:%M")
        raise MailingSendError(
            f"Отправка разрешена только с {start} по {end}. Сейчас рассылка в статусе «{mailing.status}»."
        )

    recipients = list(mailing.recipients.all())
    if not recipients:
        raise MailingSendError("У рассылки нет получателей.")

    message = mailing.message
    attempts = []
    for recipient in recipients:
        try:
            send_mail(
                subject=message.subject,
                message=message.body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient.email],
                fail_silently=False,
            )
        except (smtplib.SMTPException, OSError, BadHeaderError) as exc:
            attempts.append(
                MailingAttempt(
                    mailing=mailing,
                    recipient=recipient,
                    status=MailingAttempt.Status.FAILURE,
                    server_response=str(exc) or exc.__class__.__name__,
                )
            )
        else:
            attempts.append(
                MailingAttempt(
                    mailing=mailing,
                    recipient=recipient,
                    status=MailingAttempt.Status.SUCCESS,
                    server_response=f"Письмо для {recipient.email} принято почтовым сервером.",
                )
            )

    MailingAttempt.objects.bulk_create(attempts)
    # bulk_create не вызывает сигналы, поэтому кеш статистики сбрасываем сами.
    bump_version("stats")
    return attempts


# --- Кеш: версии разделов ---

def _version_key(section):
    return f"{section}_version"


def get_version(section):
    version = cache.get(_version_key(section))
    if version is None:
        version = 1
        cache.set(_version_key(section), version, None)
    return version


def bump_version(*sections):
    for section in sections:
        try:
            cache.incr(_version_key(section))
        except ValueError:
            cache.set(_version_key(section), 2, None)


def get_cached(section, scope, builder, timeout=None):
    """Достаёт данные раздела из кеша; если их нет — строит builder() и кладёт в кеш."""
    key = f"{section}_v{get_version(section)}_{scope}"
    data = cache.get(key)
    if data is None:
        data = builder()
        cache.set(key, data, timeout or settings.LIST_CACHE_TIMEOUT)
    return data


def user_scope(user, view_all_permission):
    """Менеджеры видят все данные (общий кеш), пользователи — только свои."""
    return "all" if user.has_perm(view_all_permission) else f"user_{user.pk}"


# --- Данные для страниц (из кеша) ---

def get_recipients(user):
    scope = user_scope(user, "mailings.can_view_all_recipients")

    def build():
        qs = Recipient.objects.select_related("owner")
        return list(qs if scope == "all" else qs.filter(owner=user))

    return get_cached("recipients", scope, build)


def get_messages(user):
    scope = user_scope(user, "mailings.can_view_all_messages")

    def build():
        qs = Message.objects.select_related("owner")
        return list(qs if scope == "all" else qs.filter(owner=user))

    return get_cached("messages", scope, build)


def get_mailings(user):
    if Mailing.refresh_statuses():
        bump_version("mailings")
    scope = user_scope(user, "mailings.can_view_all_mailings")

    def build():
        qs = Mailing.objects.select_related("message", "owner").annotate(recipients_count=Count("recipients"))
        return list(qs if scope == "all" else qs.filter(owner=user))

    return get_cached("mailings", scope, build)


def get_home_stats():
    """Показатели главной страницы: всего рассылок, активных, уникальных получателей."""
    stats = cache.get(HOME_STATS_KEY)
    if stats is None:
        Mailing.refresh_statuses()
        now = timezone.now()
        stats = {
            "mailings_total": Mailing.objects.count(),
            "mailings_active": Mailing.objects.filter(
                status=Mailing.Status.STARTED,
                start_time__lte=now,
                end_time__gte=now,
                is_active=True,
            ).count(),
            "recipients_unique": Recipient.objects.values("email").distinct().count(),
        }
        cache.set(HOME_STATS_KEY, stats, settings.HOME_STATS_CACHE_TIMEOUT)
    return stats


def get_user_stats(user):
    """Статистика по рассылкам пользователя: попытки успешные/неуспешные и т. д."""

    def build():
        success = Count("attempts", filter=Q(attempts__status=MailingAttempt.Status.SUCCESS))
        failure = Count("attempts", filter=Q(attempts__status=MailingAttempt.Status.FAILURE))
        mailings = list(
            Mailing.objects.filter(owner=user)
            .select_related("message")
            .annotate(success_count=success, failure_count=failure)
            .order_by("-start_time")
        )
        totals = MailingAttempt.objects.filter(mailing__owner=user).aggregate(
            success=Count("id", filter=Q(status=MailingAttempt.Status.SUCCESS)),
            failure=Count("id", filter=Q(status=MailingAttempt.Status.FAILURE)),
        )
        return {
            "mailings": mailings,
            "mailings_total": len(mailings),
            "attempts_success": totals["success"],
            "attempts_failure": totals["failure"],
            "attempts_total": totals["success"] + totals["failure"],
            # отправленные сообщения — успешные попытки
            "messages_sent": totals["success"],
        }

    return get_cached("stats", f"user_{user.pk}", build)
