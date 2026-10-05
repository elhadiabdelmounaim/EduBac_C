from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('quizzes', '0006_quiz_classroom'),
        ('whiteboard', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='QuizCorrectionBoard',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('data', models.JSONField(blank=True, default=dict)),
                ('schema_version', models.PositiveSmallIntegerField(default=1)),
                ('revision', models.PositiveIntegerField(default=1)),
                ('mode', models.CharField(choices=[('hint', 'Indice'), ('full', 'Correction complète')], default='full', max_length=10)),
                ('generated_by_ai', models.BooleanField(default=False)),
                ('warning', models.CharField(blank=True, max_length=300)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('attempt', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='correction_boards', to='quizzes.attempt')),
                ('question', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='correction_boards', to='quizzes.question')),
            ],
            options={
                'verbose_name': 'Tableau de correction',
                'verbose_name_plural': 'Tableaux de correction',
                'ordering': ['-updated_at'],
                'unique_together': {('attempt', 'question')},
            },
        ),
    ]
