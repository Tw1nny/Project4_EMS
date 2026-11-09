"""
Контроллеры приложения mailings (CBV).

Права доступа:
- все страницы, кроме главной, — только для вошедших пользователей;
- пользователь видит и меняет только свои данные (owner);
- менеджер (права can_view_all_*) видит данные всех пользователей,
  но редактировать и удалять может только свои — на чужие получит 403;
- отключать рассылки может только менеджер (can_disable_mailing).
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import cache_control
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from mailings import services
from mailings.forms import MailingForm, MessageForm, RecipientForm
from mailings.models import Mailing, Message, Recipient


# --- Общие примеси ---

class OwnerQuerysetMixin:
    """Ограничивает выборку своими объектами, если нет права видеть все."""

    view_all_permission = None

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if self.view_all_permission and user.has_perm(self.view_all_permission):
            return queryset
        return queryset.filter(owner=user)


class OwnerRequiredMixin(OwnerQuerysetMixin):
    """Изменять и удалять объект может только его владелец."""

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if obj.owner_id != self.request.user.pk:
            raise PermissionDenied("Изменять и удалять можно только свои данные.")
        return obj


class OwnerCreateMixin:
    """При создании владельцем становится текущий пользователь."""

    def form_valid(self, form):
        form.instance.owner = self.request.user
        return super().form_valid(form)


class DeleteContextMixin:
    """Данные для общего шаблона подтверждения удаления."""

    delete_title = "Удаление"
    cancel_url_name = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["delete_title"] = self.delete_title
        context["cancel_url"] = reverse(self.cancel_url_name, args=[self.object.pk])
        return context


# --- Главная ---

@method_decorator(cache_control(private=True, max_age=settings.CLIENT_CACHE_MAX_AGE), name="dispatch")
class HomeView(TemplateView):
    """Главная: показатели берутся из кеша; браузер может хранить страницу 60 секунд."""

    template_name = "mailings/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(services.get_home_stats())
        return context


# --- Получатели ---

class RecipientListView(LoginRequiredMixin, ListView):
    template_name = "mailings/recipient_list.html"
    context_object_name = "recipients"

    def get_queryset(self):
        return services.get_recipients(self.request.user)


class RecipientDetailView(LoginRequiredMixin, OwnerQuerysetMixin, DetailView):
    model = Recipient
    view_all_permission = "mailings.can_view_all_recipients"


class RecipientCreateView(LoginRequiredMixin, OwnerCreateMixin, CreateView):
    model = Recipient
    form_class = RecipientForm
    success_url = reverse_lazy("mailings:recipient_list")


class RecipientUpdateView(LoginRequiredMixin, OwnerRequiredMixin, UpdateView):
    model = Recipient
    form_class = RecipientForm
    view_all_permission = "mailings.can_view_all_recipients"

    def get_success_url(self):
        return reverse("mailings:recipient_detail", args=[self.object.pk])


class RecipientDeleteView(LoginRequiredMixin, OwnerRequiredMixin, DeleteContextMixin, DeleteView):
    model = Recipient
    template_name = "confirm_delete.html"
    view_all_permission = "mailings.can_view_all_recipients"
    success_url = reverse_lazy("mailings:recipient_list")
    delete_title = "Удаление получателя"
    cancel_url_name = "mailings:recipient_detail"


# --- Сообщения ---

class MessageListView(LoginRequiredMixin, ListView):
    template_name = "mailings/message_list.html"
    context_object_name = "mail_messages"

    def get_queryset(self):
        return services.get_messages(self.request.user)


class MessageDetailView(LoginRequiredMixin, OwnerQuerysetMixin, DetailView):
    model = Message
    context_object_name = "mail_message"
    view_all_permission = "mailings.can_view_all_messages"


class MessageCreateView(LoginRequiredMixin, OwnerCreateMixin, CreateView):
    model = Message
    form_class = MessageForm
    success_url = reverse_lazy("mailings:message_list")


class MessageUpdateView(LoginRequiredMixin, OwnerRequiredMixin, UpdateView):
    model = Message
    form_class = MessageForm
    view_all_permission = "mailings.can_view_all_messages"

    def get_success_url(self):
        return reverse("mailings:message_detail", args=[self.object.pk])


class MessageDeleteView(LoginRequiredMixin, OwnerRequiredMixin, DeleteContextMixin, DeleteView):
    model = Message
    template_name = "confirm_delete.html"
    view_all_permission = "mailings.can_view_all_messages"
    success_url = reverse_lazy("mailings:message_list")
    delete_title = "Удаление сообщения"
    cancel_url_name = "mailings:message_detail"


# --- Рассылки ---

class MailingListView(LoginRequiredMixin, ListView):
    template_name = "mailings/mailing_list.html"
    context_object_name = "mailings"

    def get_queryset(self):
        return services.get_mailings(self.request.user)


class MailingDetailView(LoginRequiredMixin, OwnerQuerysetMixin, DetailView):
    model = Mailing
    view_all_permission = "mailings.can_view_all_mailings"

    def get_queryset(self):
        return super().get_queryset().select_related("message", "owner").prefetch_related("recipients")

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        obj.update_status()  # статус пересчитывается при каждом просмотре
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["attempts"] = self.object.attempts.select_related("recipient")[:50]
        context["can_send"] = self.object.can_be_sent_now()
        return context


class MailingFormMixin:
    model = Mailing
    form_class = MailingForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_success_url(self):
        return reverse("mailings:mailing_detail", args=[self.object.pk])


class MailingCreateView(LoginRequiredMixin, OwnerCreateMixin, MailingFormMixin, CreateView):
    def form_valid(self, form):
        form.instance.status = form.instance.calculate_status()
        return super().form_valid(form)


class MailingUpdateView(LoginRequiredMixin, OwnerRequiredMixin, MailingFormMixin, UpdateView):
    view_all_permission = "mailings.can_view_all_mailings"

    def form_valid(self, form):
        form.instance.status = form.instance.calculate_status()
        return super().form_valid(form)


class MailingDeleteView(LoginRequiredMixin, OwnerRequiredMixin, DeleteContextMixin, DeleteView):
    model = Mailing
    template_name = "confirm_delete.html"
    view_all_permission = "mailings.can_view_all_mailings"
    success_url = reverse_lazy("mailings:mailing_list")
    delete_title = "Удаление рассылки"
    cancel_url_name = "mailings:mailing_detail"


class MailingSendView(LoginRequiredMixin, View):
    """Ручной запуск рассылки (POST). Отправлять может только владелец."""

    def post(self, request, pk):
        mailing = get_object_or_404(Mailing.objects.select_related("message"), pk=pk)
        if mailing.owner_id != request.user.pk:
            if request.user.has_perm("mailings.can_view_all_mailings"):
                raise PermissionDenied("Запускать можно только свои рассылки.")
            raise Http404

        try:
            attempts = services.send_mailing(mailing)
        except services.MailingSendError as exc:
            messages.error(request, str(exc))
        else:
            success = sum(1 for a in attempts if a.status == a.Status.SUCCESS)
            failure = len(attempts) - success
            if failure:
                messages.warning(request, f"Рассылка отправлена: успешно — {success}, с ошибкой — {failure}.")
            else:
                messages.success(request, f"Рассылка отправлена: успешно — {success}.")
        return redirect("mailings:mailing_detail", pk=pk)


class MailingToggleView(PermissionRequiredMixin, View):
    """Отключение и включение рассылки менеджером (POST)."""

    permission_required = "mailings.can_disable_mailing"

    def post(self, request, pk):
        mailing = get_object_or_404(Mailing, pk=pk)
        mailing.is_active = not mailing.is_active
        mailing.save(update_fields=["is_active"])
        if mailing.is_active:
            messages.success(request, f"{mailing} снова включена.")
        else:
            messages.success(request, f"{mailing} отключена.")
        return redirect("mailings:mailing_detail", pk=pk)


# --- Статистика ---

class StatsView(LoginRequiredMixin, TemplateView):
    """Статистика по рассылкам текущего пользователя (данные из кеша)."""

    template_name = "mailings/stats.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(services.get_user_stats(self.request.user))
        return context

