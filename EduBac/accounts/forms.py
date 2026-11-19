from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import User, StudentProfile


class ForcedPasswordChangeForm(forms.Form):
    new_password1 = forms.CharField(
        label='Nouveau mot de passe',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'autocomplete': 'new-password',
            'class': 'form-control',
        }),
    )
    new_password2 = forms.CharField(
        label='Confirmer le nouveau mot de passe',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'autocomplete': 'new-password',
            'class': 'form-control',
        }),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('new_password1')
        password2 = cleaned_data.get('new_password2')
        if not password1 or not password2:
            return cleaned_data
        if password1 != password2:
            self.add_error('new_password2', 'Les deux mots de passe ne correspondent pas.')
            return cleaned_data
        if self.user.check_password(password1):
            self.add_error(
                'new_password1',
                'Choisissez un mot de passe différent du mot de passe temporaire.',
            )
        try:
            validate_password(password1, user=self.user)
        except ValidationError as exc:
            self.add_error('new_password1', exc)
        return cleaned_data


def _password_field(label, autocomplete='new-password'):
    return forms.CharField(
        label=label,
        strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': autocomplete, 'class': 'form-control'}),
    )


class _NewPasswordMixin:
    """Deux saisies identiques + règles de mot de passe de Django."""

    def check_new_password(self, user):
        cleaned_data = self.cleaned_data
        password1 = cleaned_data.get('new_password1')
        password2 = cleaned_data.get('new_password2')
        if not password1 or not password2:
            return
        if password1 != password2:
            self.add_error('new_password2', 'Les deux mots de passe ne correspondent pas.')
            return
        try:
            validate_password(password1, user=user)
        except ValidationError as exc:
            self.add_error('new_password1', exc)


class PasswordChangeForm(_NewPasswordMixin, forms.Form):
    """Changement volontaire depuis le profil : le mot de passe actuel est demandé."""

    old_password = _password_field('Mot de passe actuel', 'current-password')
    new_password1 = _password_field('Nouveau mot de passe')
    new_password2 = _password_field('Confirmer le nouveau mot de passe')

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        cleaned_data = super().clean()
        old = cleaned_data.get('old_password')
        if old is not None and not self.user.check_password(old):
            self.add_error('old_password', 'Mot de passe actuel incorrect.')
            return cleaned_data
        new = cleaned_data.get('new_password1')
        if new and old == new:
            self.add_error('new_password1', 'Choisissez un mot de passe différent de l’actuel.')
            return cleaned_data
        self.check_new_password(self.user)
        return cleaned_data


class RecoveryCodeForm(_NewPasswordMixin, forms.Form):
    """Mot de passe oublié : identifiant + code de récupération + nouveau mot de passe."""

    username = forms.CharField(
        label='Nom d’utilisateur ou e-mail',
        max_length=254,
        widget=forms.TextInput(attrs={'autocomplete': 'username', 'class': 'form-control'}),
    )
    code = forms.CharField(
        label='Code de récupération',
        max_length=40,
        widget=forms.TextInput(attrs={
            'autocomplete': 'off', 'autocapitalize': 'characters', 'spellcheck': 'false',
            'class': 'form-control font-monospace', 'placeholder': 'XXXX-XXXX-XXXX',
        }),
    )
    new_password1 = _password_field('Nouveau mot de passe')
    new_password2 = _password_field('Confirmer le nouveau mot de passe')

    def clean(self):
        cleaned_data = super().clean()
        # Les règles qui comparent au profil sont vérifiées une fois le compte trouvé.
        self.check_new_password(None)
        return cleaned_data


class StudentRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True, label='Adresse e-mail')
    first_name = forms.CharField(max_length=100, required=False, label='Prénom')
    last_name = forms.CharField(max_length=100, required=False, label='Nom')
    niveau = forms.ChoiceField(
        choices=StudentProfile.NIVEAU_CHOICES,
        label='Niveau scolaire',
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = 'student'
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
            StudentProfile.objects.create(
                user=user,
                niveau=self.cleaned_data['niveau'],
            )
        return user
