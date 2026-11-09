"""
Создаёт группу «Менеджеры» с правами:
- просматривать всех клиентов, сообщения и рассылки;
- отключать рассылки;
- просматривать список пользователей и блокировать их.

    python manage.py create_groups

Команду можно запускать повторно. Пользователя делают менеджером в
админке: Пользователи → пользователь → поле «Группы».
"""

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError

MANAGERS_GROUP = "Менеджеры"

MANAGER_PERMISSIONS = [
    "mailings.can_view_all_recipients",
    "mailings.can_view_all_messages",
    "mailings.can_view_all_mailings",
    "mailings.can_disable_mailing",
    "users.can_view_users",
    "users.can_block_users",
]


class Command(BaseCommand):
    help = "Создаёт группу «Менеджеры» с нужными правами"

    def handle(self, *args, **options):
        permissions = []
        for full_name in MANAGER_PERMISSIONS:
            app_label, codename = full_name.split(".")
            try:
                permissions.append(Permission.objects.get(content_type__app_label=app_label, codename=codename))
            except Permission.DoesNotExist:
                raise CommandError(f"Право {full_name} не найдено. Сначала выполните: python manage.py migrate")

        group, created = Group.objects.get_or_create(name=MANAGERS_GROUP)
        group.permissions.set(permissions)

        status = "создана" if created else "обновлена"
        self.stdout.write(self.style.SUCCESS(f"Группа «{MANAGERS_GROUP}» {status}:"))
        for full_name in MANAGER_PERMISSIONS:
            self.stdout.write(f"  - {full_name}")
