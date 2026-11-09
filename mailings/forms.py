"""
Формы приложения mailings.

- StyleFormMixin — назначает полям классы Bootstrap в __init__.
- RecipientForm, MessageForm — клиенты и сообщения.
- MailingForm — рассылка. В списках сообщений и получателей только
  данные текущего пользователя. Проверки: начало не в прошлом,
  начало раньше окончания.
"""

from django import forms
from django.utils import timezone

from mailings.models import Mailing, Message, Recipient

DATETIME_INPUT_FORMAT = "%Y-%m-%dT%H:%M"


class StyleFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxSelectMultiple):
                continue  # у списка чекбоксов классы задаются в шаблоне
            if isinstance(widget, forms.CheckboxInput):
                css_class = "form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css_class = "form-select"
            else:
                css_class = "form-control"
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{existing} {css_class}".strip()


class RecipientForm(StyleFormMixin, forms.ModelForm):
    class Meta:
        model = Recipient
        fields = ["email", "full_name", "comment"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["comment"].widget.attrs["rows"] = 3

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class MessageForm(StyleFormMixin, forms.ModelForm):
    class Meta:
        model = Message
        fields = ["subject", "body"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["body"].widget.attrs["rows"] = 8


class MailingForm(StyleFormMixin, forms.ModelForm):
    class Meta:
        model = Mailing
        fields = ["start_time", "end_time", "message", "recipients"]
        widgets = {
            "start_time": forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DATETIME_INPUT_FORMAT),
            "end_time": forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DATETIME_INPUT_FORMAT),
            "recipients": forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("start_time", "end_time"):
            self.fields[name].input_formats = [DATETIME_INPUT_FORMAT]
        if user is not None:
            self.fields["message"].queryset = Message.objects.filter(owner=user)
            self.fields["recipients"].queryset = Recipient.objects.filter(owner=user)
        self.fields["message"].empty_label = "— выберите сообщение —"

    def clean_start_time(self):
        start_time = self.cleaned_data["start_time"]
        # Прошлое запрещено для новой рассылки или если дату начала изменили.
        if (not self.instance.pk or "start_time" in self.changed_data) and start_time < timezone.now():
            raise forms.ValidationError("Дата и время начала не могут быть в прошлом.")
        return start_time

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")
        if start_time and end_time and start_time >= end_time:
            self.add_error("end_time", "Окончание рассылки должно быть позже её начала.")
        return cleaned_data
