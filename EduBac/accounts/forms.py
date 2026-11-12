from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import User, StudentProfile, TeacherProfile


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


class TeacherRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True, label='Adresse e-mail')
    first_name = forms.CharField(max_length=100, required=False, label='Prénom')
    last_name = forms.CharField(max_length=100, required=False, label='Nom')
    bio = forms.CharField(widget=forms.Textarea, required=False, label='Biographie')

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = 'teacher'
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
            TeacherProfile.objects.create(
                user=user,
                subject='Mathématiques',
                bio=self.cleaned_data.get('bio', ''),
            )
        return user
