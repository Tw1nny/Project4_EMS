import smtplib
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import Group
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from mailings import services
from mailings.forms import MailingForm
from mailings.models import Mailing, MailingAttempt, Message, Recipient
from users.models import User

PW = "Str0ng-Pass-2026"
TEST_SETTINGS = {
    "CACHES": {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
}
FMT = "%Y-%m-%dT%H:%M"


@override_settings(**TEST_SETTINGS)
class Base(TestCase):
    def setUp(self):
        cache.clear()
        call_command("create_groups", stdout=StringIO())
        self.user = User.objects.create_user("user@example.com", PW, email_verified=True)
        self.other = User.objects.create_user("other@example.com", PW, email_verified=True)
        self.manager = User.objects.create_user("manager@example.com", PW, email_verified=True)
        self.manager.groups.add(Group.objects.get(name="Менеджеры"))
        now = timezone.now()
        self.r1 = Recipient.objects.create(email="a@client.ru", full_name="Анна", owner=self.user)
        self.r2 = Recipient.objects.create(email="b@client.ru", full_name="Борис", owner=self.user)
        self.r_other = Recipient.objects.create(email="c@client.ru", full_name="Чужой", owner=self.other)
        self.msg = Message.objects.create(subject="Акция", body="Скидки!", owner=self.user)
        self.running = Mailing.objects.create(
            start_time=now - timedelta(hours=1), end_time=now + timedelta(hours=1), message=self.msg, owner=self.user
        )
        self.running.recipients.set([self.r1, self.r2])
        self.future = Mailing.objects.create(
            start_time=now + timedelta(days=1), end_time=now + timedelta(days=2), message=self.msg, owner=self.user
        )
        self.future.recipients.set([self.r1])
        cache.clear()


class StatusTests(Base):
    def test_update_status(self):
        self.assertEqual(self.running.update_status(), "Запущена")
        self.assertEqual(self.future.update_status(), "Создана")
        self.future.start_time = timezone.now() - timedelta(days=3)
        self.future.end_time = timezone.now() - timedelta(days=2)
        self.future.save()
        self.assertEqual(self.future.update_status(), "Завершена")
        self.assertEqual(Mailing.objects.get(pk=self.future.pk).status, "Завершена")

    def test_detail_recalculates_status(self):
        Mailing.objects.filter(pk=self.running.pk).update(status="Создана")
        self.client.force_login(self.user)
        self.assertContains(self.client.get(f"/mailings/{self.running.pk}/"), "Запущена")
        self.assertEqual(Mailing.objects.get(pk=self.running.pk).status, "Запущена")


class FormValidationTests(Base):
    def data(self, start, end):
        return {
            "start_time": start.strftime(FMT),
            "end_time": end.strftime(FMT),
            "message": self.msg.pk,
            "recipients": [self.r1.pk],
        }

    def test_past_start_and_order(self):
        now = timezone.localtime()
        form = MailingForm(data=self.data(now - timedelta(days=1), now + timedelta(days=1)), user=self.user)
        self.assertIn("не могут быть в прошлом", form.errors["start_time"][0])
        form = MailingForm(data=self.data(now + timedelta(days=2), now + timedelta(days=1)), user=self.user)
        self.assertIn("позже её начала", form.errors["end_time"][0])
        form = MailingForm(data=self.data(now + timedelta(days=1), now + timedelta(days=2)), user=self.user)
        self.assertTrue(form.is_valid(), form.errors)

    def test_only_own_choices(self):
        form = MailingForm(user=self.user)
        self.assertNotIn(self.r_other, form.fields["recipients"].queryset)
        data = self.data(timezone.localtime() + timedelta(days=1), timezone.localtime() + timedelta(days=2))
        data["recipients"] = [self.r_other.pk]
        self.assertFalse(MailingForm(data=data, user=self.user).is_valid())

    def test_edit_running_mailing_keeps_start(self):
        start = timezone.localtime(self.running.start_time).replace(second=0, microsecond=0)
        Mailing.objects.filter(pk=self.running.pk).update(start_time=start)
        self.running.refresh_from_db()
        data = self.data(start, timezone.localtime() + timedelta(hours=5))
        self.assertTrue(MailingForm(data=data, instance=self.running, user=self.user).is_valid())


class SendTests(Base):
    def test_send_success_creates_attempts_in_batch(self):
        with mock.patch.object(MailingAttempt.objects, "bulk_create", wraps=MailingAttempt.objects.bulk_create) as bulk:
            attempts = services.send_mailing(self.running)
        bulk.assert_called_once()
        self.assertEqual(len(attempts), 2)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(MailingAttempt.objects.filter(mailing=self.running, status="Успешно").count(), 2)

    def test_send_failure_saved_with_error_text(self):
        def fake_send(*args, recipient_list, **kwargs):
            if recipient_list == ["b@client.ru"]:
                raise smtplib.SMTPRecipientsRefused({"b@client.ru": (550, b"Mailbox not found")})
            return 1

        with mock.patch("mailings.services.send_mail", side_effect=fake_send):
            services.send_mailing(self.running)
        fail = MailingAttempt.objects.get(status="Не успешно")
        self.assertEqual(fail.recipient, self.r2)
        self.assertIn("Mailbox not found", fail.server_response)
        self.assertEqual(MailingAttempt.objects.filter(status="Успешно").count(), 1)

    def test_send_outside_period_is_rejected(self):
        with self.assertRaisesMessage(services.MailingSendError, "Отправка разрешена только"):
            services.send_mailing(self.future)
        self.client.force_login(self.user)
        r = self.client.post(f"/mailings/{self.future.pk}/send/", follow=True)
        self.assertContains(r, "Отправка разрешена только")
        self.assertFalse(MailingAttempt.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_send_view(self):
        self.client.force_login(self.user)
        r = self.client.post(f"/mailings/{self.running.pk}/send/", follow=True)
        self.assertContains(r, "успешно — 2")
        self.assertContains(r, "Успешно")
        # чужой пользователь не может запустить
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(f"/mailings/{self.running.pk}/send/").status_code, 404)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.post(f"/mailings/{self.running.pk}/send/").status_code, 403)

    def test_command(self):
        out = StringIO()
        call_command("send_mailing", str(self.running.pk), stdout=out)
        self.assertIn("успешно — 2", out.getvalue())
        out = StringIO()
        call_command("send_mailing", str(self.future.pk), stdout=out)
        self.assertIn("Отправка разрешена только", out.getvalue())
        out = StringIO()
        call_command("send_mailing", "--all", stdout=out)
        self.assertIn(f"№{self.running.pk}", out.getvalue())


class AccessTests(Base):
    def test_anonymous_redirected(self):
        for url in ["/recipients/", "/messages/", "/mailings/", "/stats/", "/mailings/create/"]:
            self.assertRedirects(self.client.get(url), f"/users/login/?next={url}", fetch_redirect_response=False)

    def test_user_sees_only_own(self):
        self.client.force_login(self.other)
        r = self.client.get("/recipients/")
        self.assertContains(r, "Чужой")
        self.assertNotContains(r, "Анна")
        self.assertEqual(self.client.get(f"/recipients/{self.r1.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"/mailings/{self.running.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"/recipients/{self.r1.pk}/delete/").status_code, 404)

    def test_owner_crud(self):
        self.client.force_login(self.user)
        r = self.client.post("/recipients/create/", {"email": "New@Client.ru", "full_name": "Новый", "comment": ""})
        self.assertRedirects(r, "/recipients/")
        new = Recipient.objects.get(email="new@client.ru")
        self.assertEqual(new.owner, self.user)
        r = self.client.post(f"/recipients/{new.pk}/update/", {"email": "new@client.ru", "full_name": "Изменён"})
        self.assertRedirects(r, f"/recipients/{new.pk}/")
        self.client.post(f"/recipients/{new.pk}/delete/")
        self.assertFalse(Recipient.objects.filter(pk=new.pk).exists())

        start = timezone.localtime() + timedelta(days=1)
        r = self.client.post(
            "/mailings/create/",
            {"start_time": start.strftime(FMT), "end_time": (start + timedelta(days=1)).strftime(FMT),
             "message": self.msg.pk, "recipients": [self.r1.pk, self.r2.pk]},
        )
        mailing = Mailing.objects.latest("pk")
        self.assertRedirects(r, f"/mailings/{mailing.pk}/")
        self.assertEqual(mailing.owner, self.user)
        self.assertEqual(mailing.status, "Создана")
        self.assertEqual(mailing.recipients.count(), 2)

    def test_manager_views_all_but_cannot_edit(self):
        self.client.force_login(self.manager)
        r = self.client.get("/recipients/")
        self.assertContains(r, "Анна")
        self.assertContains(r, "Чужой")
        self.assertContains(self.client.get("/mailings/"), "Акция")
        self.assertEqual(self.client.get(f"/mailings/{self.running.pk}/").status_code, 200)
        for url in [f"/recipients/{self.r1.pk}/update/", f"/mailings/{self.running.pk}/update/",
                    f"/messages/{self.msg.pk}/delete/"]:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.client.post(f"/recipients/{self.r1.pk}/delete/")
        self.assertTrue(Recipient.objects.filter(pk=self.r1.pk).exists())

    def test_manager_disables_mailing(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(f"/mailings/{self.running.pk}/toggle/").status_code, 403)
        self.client.force_login(self.manager)
        self.client.post(f"/mailings/{self.running.pk}/toggle/")
        self.running.refresh_from_db()
        self.assertFalse(self.running.is_active)
        with self.assertRaisesMessage(services.MailingSendError, "отключена"):
            services.send_mailing(self.running)


class HomeAndStatsTests(Base):
    def test_home_stats(self):
        r = self.client.get("/")
        self.assertEqual(r.context["mailings_total"], 2)
        self.assertEqual(r.context["mailings_active"], 1)
        self.assertEqual(r.context["recipients_unique"], 3)
        # клиентский кеш
        self.assertIn("max-age=60", r["Cache-Control"])
        self.assertIn("private", r["Cache-Control"])

    def test_stats_page(self):
        services.send_mailing(self.running)
        self.client.force_login(self.user)
        r = self.client.get("/stats/")
        self.assertEqual(r.context["messages_sent"], 2)
        self.assertEqual(r.context["attempts_success"], 2)
        self.assertEqual(r.context["attempts_failure"], 0)
        self.assertEqual(r.context["mailings_total"], 2)


class CacheTests(Base):
    def test_home_stats_from_cache(self):
        services.get_home_stats()
        with self.assertNumQueries(0):
            stats = services.get_home_stats()
        self.assertEqual(stats["mailings_total"], 2)
        Recipient.objects.create(email="d@client.ru", full_name="Дмитрий", owner=self.user)
        self.assertEqual(services.get_home_stats()["recipients_unique"], 4)

    def test_lists_from_cache_and_invalidated(self):
        services.get_recipients(self.user)
        with self.assertNumQueries(0):
            names = [r.full_name for r in services.get_recipients(self.user)]
        self.assertEqual(sorted(names), ["Анна", "Борис"])
        self.r1.full_name = "Анна-Мария"
        self.r1.save()
        self.assertIn("Анна-Мария", [r.full_name for r in services.get_recipients(self.user)])

    def test_stats_cache_reset_after_send(self):
        self.assertEqual(services.get_user_stats(self.user)["messages_sent"], 0)
        services.send_mailing(self.running)
        self.assertEqual(services.get_user_stats(self.user)["messages_sent"], 2)
