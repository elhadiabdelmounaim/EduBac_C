from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User, StudentProfile, TeacherProfile


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
