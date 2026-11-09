"""
Сброс кеша при изменении данных: после сохранения или удаления клиента,
сообщения или рассылки увеличивается версия соответствующего раздела
кеша (см. mailings/services.py), и страницы сразу показывают новые данные.
"""

from django.core.cache import cache
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from mailings.models import Mailing, Message, Recipient
from mailings.services import HOME_STATS_KEY, bump_version


@receiver(post_save, sender=Recipient)
@receiver(post_delete, sender=Recipient)
def recipient_changed(sender, **kwargs):
    bump_version("recipients", "mailings")
    cache.delete(HOME_STATS_KEY)


@receiver(post_save, sender=Message)
@receiver(post_delete, sender=Message)
def message_changed(sender, **kwargs):
    bump_version("messages", "mailings", "stats")


@receiver(post_save, sender=Mailing)
@receiver(post_delete, sender=Mailing)
def mailing_changed(sender, **kwargs):
    bump_version("mailings", "stats")
    cache.delete(HOME_STATS_KEY)


@receiver(m2m_changed, sender=Mailing.recipients.through)
def mailing_recipients_changed(sender, **kwargs):
    bump_version("mailings")
