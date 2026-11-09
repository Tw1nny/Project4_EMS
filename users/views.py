"""
Контроллеры приложения users.

- RegisterView: регистрация. Аккаунт создаётся неактивным, на почту
  уходит письмо со ссылкой подтверждения. Если письмо отправить не
  удалось, аккаунт удаляется, чтобы можно было зарегистрироваться снова.
- EmailConfirmView: подтверждение email по ссылке из письма.
- UserLoginView / LogoutView: вход по email и паролю, выход.
- Восстановление пароля: стандартные PasswordReset*View со своими
  шаблонами (см. users/urls.py).
- ProfileView: редактирование имени и фамилии.
- UserListView / UserBlockView: для менеджеров — список пользователей
  и блокировка/разблокировка.
"""

import logging
import smtplib

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.core.mail import BadHeaderError, send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from users.forms import UserLoginForm, UserProfileForm, UserRegisterForm
from users.models import User
from users.tokens import email_confirmation_token

logger = logging.getLogger(__name__)


class RegisterView(CreateView):
    model = User
    form_class = UserRegisterForm
    template_name = "users/register.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("mailings:home")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save(commit=False)
        user.is_active = False
        user.email_verified = False
        user.save()

        try:
            self.send_confirmation_email(user)
        except (smtplib.SMTPException, OSError, BadHeaderError):
            logger.exception("Не удалось отправить письмо подтверждения на %s", user.email)
            user.delete()
            messages.error(
                self.request,
                "Не удалось отправить письмо для подтверждения email. Попробуйте зарегистрироваться позже.",
            )
            return self.form_invalid(form)

        return render(self.request, "users/register_done.html", {"email": user.email})

    def send_confirmation_email(self, user):
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = email_confirmation_token.make_token(user)
        link = self.request.build_absolute_uri(reverse("users:confirm_email", args=[uid, token]))
        body = render_to_string("users/emails/confirm_email.txt", {"user": user, "link": link})
        send_mail(
            subject="Подтверждение регистрации в сервисе рассылок",
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )


class EmailConfirmView(View):
    def get(self, request, uidb64, token):
        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None

        if user is None or user.email_verified or not email_confirmation_token.check_token(user, token):
            return render(request, "users/confirm_email_invalid.html", status=400)

        user.email_verified = True
        user.is_active = True
        user.save(update_fields=["email_verified", "is_active"])
        login(request, user)
        messages.success(request, "Email подтверждён. Добро пожаловать!")
        return redirect("mailings:home")


class UserLoginView(LoginView):
    form_class = UserLoginForm
    template_name = "users/login.html"
    redirect_authenticated_user = True


class ProfileView(LoginRequiredMixin, UpdateView):
    model = User
    form_class = UserProfileForm
    template_name = "users/profile.html"
    success_url = reverse_lazy("users:profile")

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, "Профиль сохранён.")
        return super().form_valid(form)


class UserListView(PermissionRequiredMixin, ListView):
    """Список пользователей сервиса — только для менеджеров."""

    permission_required = "users.can_view_users"
    model = User
    template_name = "users/user_list.html"
    context_object_name = "users_list"

    def get_queryset(self):
        return User.objects.prefetch_related("groups").order_by("email")


class UserBlockView(PermissionRequiredMixin, View):
    """Блокировка и разблокировка пользователя (POST) — только для менеджеров."""

    permission_required = "users.can_block_users"

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        if user == request.user:
            raise PermissionDenied("Нельзя заблокировать самого себя.")
        if user.is_superuser:
            raise PermissionDenied("Нельзя заблокировать администратора.")
        if not user.email_verified:
            messages.warning(request, f"{user.email} ещё не подтвердил email — блокировать нечего.")
            return redirect("users:user_list")

        user.is_active = not user.is_active
        user.save(update_fields=["is_active"])
        if user.is_active:
            messages.success(request, f"Пользователь {user.email} разблокирован.")
        else:
            messages.success(request, f"Пользователь {user.email} заблокирован.")
        return redirect("users:user_list")
