from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('classrooms', '0002_classroom_is_active'),
        ('quizzes', '0005_quiz_publish_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='quiz',
            name='classroom',
            field=models.ForeignKey(
                blank=True,
                help_text='Classe à laquelle ce quiz a été envoyé (si applicable).',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='quizzes',
                to='classrooms.classroom',
                verbose_name='Classe destinataire',
            ),
        ),
    ]
