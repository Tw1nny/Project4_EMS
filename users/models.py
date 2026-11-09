"""
Модель пользователя сервиса.

- Вход по email (USERNAME_FIELD = "email"), поля username нет.
- email_verified — подтверждён ли email. До подтверждения аккаунт
  неактивен (is_active=False) и войти нельзя.
- is_active также используется для блокировки: менеджер блокирует
  пользователя, снимая is_active.
- Права can_view_users и can_block_users выдаются группе «Менеджеры».
"""

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Необходимо указать email.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("email_verified", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("У суперпользователя должно быть is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("У суперпользователя должно быть is_superuser=True.")
        return self._create_user(email, password, **extra_fields)

    def get_by_natural_key(self, username):
        # Вход без учёта регистра email.
        return self.get(**{f"{self.model.USERNAME_FIELD}__iexact": username})


class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True, verbose_name="Email")
    email_verified = models.BooleanField(default=False, verbose_name="Email подтверждён")

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
        ordering = ["email"]
        permissions = [
            ("can_view_users", "Может просматривать список пользователей"),
            ("can_block_users", "Может блокировать пользователей"),
        ]

    def __str__(self):
        return self.email

    @property
    def is_manager(self):
        return self.has_perm("users.can_view_users")
