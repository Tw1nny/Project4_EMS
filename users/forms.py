"""
Формы приложения users. Стили Bootstrap назначаются в __init__ через
StyleFormMixin (mailings/forms.py).
"""

from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordResetForm,
    SetPasswordForm,
    UserChangeForm,
    UserCreationForm,
)

from mailings.forms import StyleFormMixin
from users.models import User


class UserRegisterForm(StyleFormMixin, UserCreationForm):
    class Meta:
        model = User
        fields = ("email",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs.update({"placeholder": "you@example.com", "autofocus": True})
        self.fields["password1"].label = "Пароль"
        self.fields["password2"].label = "Подтверждение пароля"
        self.fields["password2"].help_text = "Введите тот же пароль ещё раз."

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Пользователь с таким email уже зарегистрирован.")
        return email


class UserLoginForm(StyleFormMixin, AuthenticationForm):
    error_messages = {
        "invalid_login": (
            "Неверный email или пароль. Если вы только что зарегистрировались, "
            "сначала подтвердите email по ссылке из письма."
        ),
        "inactive": "Аккаунт не активен.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email"
        self.fields["username"].widget.attrs["placeholder"] = "you@example.com"
        self.fields["password"].label = "Пароль"


class UserProfileForm(StyleFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name")


class StyledPasswordResetForm(StyleFormMixin, PasswordResetForm):
    pass


class StyledSetPasswordForm(StyleFormMixin, SetPasswordForm):
    pass


class UserAdminCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("email",)


class UserAdminChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"
