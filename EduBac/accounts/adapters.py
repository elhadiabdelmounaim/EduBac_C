"""
Adapters allauth personnalisés pour EduBac.
Gèrent la création des profils StudentProfile / TeacherProfile
lors de l'inscription classique ou via OAuth2 (Google...).
"""

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.urls import reverse
from .models import StudentProfile, TeacherProfile


class EduBacAccountAdapter(DefaultAccountAdapter):
    """Adapter pour les inscriptions classiques (email/password)."""

    def save_user(self, request, user, form, commit=True):
        """
        Appelé lors de l'inscription classique.
        Le rôle est déterminé par le formulaire ou par défaut 'student'.
        """
        user = super().save_user(request, user, form, commit=False)

        # Rôle par défaut = élève (sauf si fourni explicitement)
        role = form.cleaned_data.get('role', 'student') if hasattr(form, 'cleaned_data') else 'student'
        if role not in ('student', 'teacher'):
            role = 'student'
        user.role = role

        if commit:
            user.save()
            self._create_profile(user, form)
        return user

    def _create_profile(self, user, form=None):
        if user.role == 'teacher':
            TeacherProfile.objects.get_or_create(
                user=user,
                defaults={
                    'subject': 'Mathématiques',
                    'bio': '',
                },
            )
        else:
            niveau = 'tronc_commun'
            if form and hasattr(form, 'cleaned_data'):
                niveau = form.cleaned_data.get('niveau', 'tronc_commun')
            StudentProfile.objects.get_or_create(
                user=user,
                defaults={'niveau': niveau},
            )

    def get_login_redirect_url(self, request):
        return reverse('accounts:dashboard')

    def get_signup_redirect_url(self, request):
        return reverse('accounts:dashboard')


class EduBacSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Adapter pour les connexions OAuth2 (Google, etc.).
    Par défaut, tout nouvel utilisateur social devient élève.
    Il pourra compléter son profil ensuite.
    """

    def pre_social_login(self, request, sociallogin):
        """
        Si l'email existe déjà en base, on lie le compte social
        à l'utilisateur existant (évite les doublons).
        """
        if sociallogin.is_existing:
            return

        email = sociallogin.account.extra_data.get('email')
        if not email:
            return

        from accounts.models import User
        try:
            user = User.objects.get(email__iexact=email)
            sociallogin.connect(request, user)
        except User.DoesNotExist:
            pass

    def save_user(self, request, sociallogin, form=None):
        """
        Création d'un nouvel utilisateur via OAuth2.
        Rôle par défaut = student. Profil créé automatiquement.
        """
        user = super().save_user(request, sociallogin, form)

        # Forcer le rôle élève pour les inscriptions sociales
        # (l'utilisateur pourra demander un changement de rôle plus tard)
        if not user.role or user.role not in ('student', 'teacher'):
            user.role = 'student'
            user.save(update_fields=['role'])

        # Créer le profil correspondant s'il n'existe pas
        if user.role == 'teacher':
            TeacherProfile.objects.get_or_create(
                user=user,
                defaults={'subject': 'Mathématiques'},
            )
        else:
            StudentProfile.objects.get_or_create(
                user=user,
                defaults={'niveau': 'tronc_commun'},
            )

        return user

    def get_connect_redirect_url(self, request, socialaccount):
        return reverse('accounts:dashboard')
