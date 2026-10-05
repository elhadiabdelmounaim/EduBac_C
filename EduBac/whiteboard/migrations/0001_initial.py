from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('classrooms', '0002_classroom_is_active'),
        ('education', '0002_lesson_faq_lesson_summary'),
    ]

    operations = [
        migrations.CreateModel(
            name='WhiteboardBoard',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(default='Nouveau tableau', max_length=200)),
                ('content', models.JSONField(blank=True, default=dict)),
                ('students_can_edit', models.BooleanField(default=False, verbose_name='Les élèves peuvent dessiner')),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('classroom', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='whiteboards', to='classrooms.classroom', verbose_name='Classe')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='whiteboards_created', to=settings.AUTH_USER_MODEL)),
                ('lesson', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='whiteboards', to='education.lesson', verbose_name='Leçon')),
            ],
            options={
                'verbose_name': 'Whiteboard',
                'verbose_name_plural': 'Whiteboards',
                'ordering': ['-updated_at'],
            },
        ),
    ]
