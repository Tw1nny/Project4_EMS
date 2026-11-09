import re
from io import StringIO

from django.contrib.auth.models import Group
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings

from users.models import User

PW = "Str0ng-Pass-2026"
TEST_SETTINGS = {
    "CACHES": {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
}


def link_from_last_email():
    return re.search(r"http://testserver(\S+)", mail.outbox[-1].body).group(1)


@override_settings(**TEST_SETTINGS)
class RegistrationTests(TestCase):
    def register(self, **kw):
        data = {"email": "new@example.com", "password1": PW, "password2": PW}
        data.update(kw)
        return self.client.post("/users/register/", data)

    def test_register_confirm_login(self):
        r = self.register()
        self.assertContains(r, "Проверьте почту")
        user = User.objects.get(email="new@example.com")
        self.assertFalse(user.is_active)
        self.assertFalse(user.email_verified)
        self.assertEqual(len(mail.outbox), 1)

        # до подтверждения войти нельзя
        r = self.client.post("/users/login/", {"username": "new@example.com", "password": PW})
        self.assertContains(r, "подтвердите email")

        link = link_from_last_email()
        r = self.client.get(link)
        self.assertRedirects(r, "/")
        user.refresh_from_db()
        self.assertTrue(user.is_active and user.email_verified)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

        # повторно ссылка не работает
        self.client.logout()
        self.assertEqual(self.client.get(link).status_code, 400)

        # вход и выход
        r = self.client.post("/users/login/", {"username": "New@Example.com", "password": PW})
        self.assertRedirects(r, "/")
        r = self.client.post("/users/logout/")
        self.assertRedirects(r, "/")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_validation_errors(self):
        r = self.register(password2="Other-Pass-2026")
        self.assertContains(r, "Введенные пароли не совпадают")
        User.objects.create_user("taken@example.com", PW)
        r = self.register(email="TAKEN@example.com")
        self.assertContains(r, "уже зарегистрирован")
        self.assertEqual(User.objects.count(), 1)

    def test_wrong_password(self):
        User.objects.create_user("u@example.com", PW, email_verified=True)
        r = self.client.post("/users/login/", {"username": "u@example.com", "password": "wrong"})
        self.assertContains(r, "Неверный email или пароль")


@override_settings(**TEST_SETTINGS)
class PasswordResetTests(TestCase):
    def test_reset_flow(self):
        User.objects.create_user("u@example.com", PW, email_verified=True)
        r = self.client.post("/users/password-reset/", {"email": "u@example.com"})
        self.assertRedirects(r, "/users/password-reset/done/")
        self.assertEqual(len(mail.outbox), 1)
        link = link_from_last_email()
        r = self.client.get(link, follow=True)
        set_url = r.redirect_chain[-1][0]
        r = self.client.post(set_url, {"new_password1": "New-Pass-2026!", "new_password2": "New-Pass-2026!"})
        self.assertRedirects(r, "/users/password-reset/complete/")
        self.assertTrue(self.client.login(username="u@example.com", password="New-Pass-2026!"))


@override_settings(**TEST_SETTINGS)
class ManagerTests(TestCase):
    def setUp(self):
        call_command("create_groups", stdout=StringIO())
        self.manager = User.objects.create_user("manager@example.com", PW, email_verified=True)
        self.manager.groups.add(Group.objects.get(name="Менеджеры"))
        self.user = User.objects.create_user("user@example.com", PW, email_verified=True)

    def test_user_list_access(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/users/").status_code, 403)
        self.client.force_login(self.manager)
        r = self.client.get("/users/")
        self.assertContains(r, "user@example.com")
        self.assertContains(r, "Заблокировать")

    def test_block_and_unblock(self):
        self.client.force_login(self.manager)
        self.client.post(f"/users/{self.user.pk}/block/")
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertFalse(self.client.login(username="user@example.com", password=PW))
        self.client.force_login(self.manager)
        self.client.post(f"/users/{self.user.pk}/block/")
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_cannot_block_self_or_by_regular_user(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.client.post(f"/users/{self.manager.pk}/block/").status_code, 403)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(f"/users/{self.manager.pk}/block/").status_code, 403)
