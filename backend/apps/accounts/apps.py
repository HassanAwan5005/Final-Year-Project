from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Accounts & Authentication"

    def ready(self):
        # Registers the OpenAPI extension for SnapSphereJWTAuthentication.
        from apps.accounts import schema  # noqa: F401
