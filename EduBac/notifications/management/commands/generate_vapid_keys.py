from django.core.management.base import BaseCommand

from notifications.push import generate_vapid_keys


class Command(BaseCommand):
    help = "Génère les clés VAPID des notifications sur le téléphone (à copier dans .env, une seule fois)."

    def handle(self, *args, **options):
        public, private = generate_vapid_keys()
        self.stdout.write("Copiez ces lignes dans .env (la clé privée est secrète, ne la commitez pas) :\n")
        self.stdout.write(f"WEBPUSH_VAPID_PUBLIC_KEY={public}")
        self.stdout.write(f"WEBPUSH_VAPID_PRIVATE_KEY={private}")
        self.stdout.write("WEBPUSH_CONTACT=mailto:votre-adresse@exemple.com")
        self.stdout.write(self.style.WARNING(
            "\nNe changez plus ces clés ensuite : les téléphones déjà abonnés ne recevraient plus rien."
        ))
