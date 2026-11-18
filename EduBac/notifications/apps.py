from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'notifications'
    verbose_name = 'Notifications'

    def ready(self):
        import notifications.signals  # noqa: F401
        import notifications.push  # noqa: F401  (envoi après la réponse HTTP)
