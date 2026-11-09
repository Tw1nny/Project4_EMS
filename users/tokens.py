"""
Токен для ссылки подтверждения email.

Хеш зависит от email_verified и is_active, поэтому после подтверждения
ссылка перестаёт работать, а заблокированный пользователь не сможет
«разблокироваться» повторным переходом по старой ссылке.
"""

from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailConfirmationTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{user.email}{timestamp}{user.is_active}{user.email_verified}"


email_confirmation_token = EmailConfirmationTokenGenerator()
