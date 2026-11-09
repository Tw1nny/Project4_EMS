from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from users import views
from users.forms import StyledPasswordResetForm, StyledSetPasswordForm

app_name = "users"

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("confirm/<uidb64>/<token>/", views.EmailConfirmView.as_view(), name="confirm_email"),
    path("login/", views.UserLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    # Восстановление пароля
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            form_class=StyledPasswordResetForm,
            template_name="users/password_reset_form.html",
            email_template_name="users/emails/password_reset_email.txt",
            subject_template_name="users/emails/password_reset_subject.txt",
            success_url=reverse_lazy("users:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(template_name="users/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "password-reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            form_class=StyledSetPasswordForm,
            template_name="users/password_reset_confirm.html",
            success_url=reverse_lazy("users:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(template_name="users/password_reset_complete.html"),
        name="password_reset_complete",
    ),
    # Для менеджеров
    path("", views.UserListView.as_view(), name="user_list"),
    path("<int:pk>/block/", views.UserBlockView.as_view(), name="user_block"),
]
