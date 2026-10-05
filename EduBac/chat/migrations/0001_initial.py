from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('classrooms', '0002_classroom_is_active'),
    ]

    operations = [
        migrations.CreateModel(
            name='ClassChatRoom',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('classroom', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='chat_room', to='classrooms.classroom', verbose_name='Classe')),
            ],
            options={
                'verbose_name': 'Salon de discussion',
                'verbose_name_plural': 'Salons de discussion',
            },
        ),
        migrations.CreateModel(
            name='ChatMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('body', models.TextField(verbose_name='Message')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('room', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='chat.classchatroom', verbose_name='Salon')),
                ('sender', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chat_messages', to=settings.AUTH_USER_MODEL, verbose_name='Expéditeur')),
            ],
            options={
                'verbose_name': 'Message',
                'verbose_name_plural': 'Messages',
                'ordering': ['created_at'],
            },
        ),
        migrations.CreateModel(
            name='ChatReadState',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('last_read_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('room', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='read_states', to='chat.classchatroom')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chat_read_states', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'État de lecture',
                'verbose_name_plural': 'États de lecture',
                'unique_together': {('room', 'user')},
            },
        ),
    ]
