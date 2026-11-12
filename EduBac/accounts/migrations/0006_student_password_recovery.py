from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_user_approval_status_alter_user_email'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='must_change_password',
            field=models.BooleanField(
                default=False,
                verbose_name='Doit changer son mot de passe',
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='password_reset_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name='Dernière réinitialisation administrateur',
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='password_session_version',
            field=models.PositiveIntegerField(default=0, editable=False),
        ),
        migrations.CreateModel(
            name='StudentPasswordResetEvent',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('student_username', models.CharField(max_length=150)),
                ('administrator_id_snapshot', models.PositiveBigIntegerField()),
                ('administrator_username', models.CharField(max_length=150)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'administrator',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='student_password_resets',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'student',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='password_reset_events',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'verbose_name': 'Réinitialisation de mot de passe élève',
                'verbose_name_plural': 'Réinitialisations de mots de passe élèves',
                'ordering': ('-created_at',),
            },
        ),
    ]
