from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0002_chatmessage_attachment'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatmessage',
            name='is_pinned',
            field=models.BooleanField(default=False, verbose_name='Épinglé'),
        ),
        migrations.AddField(
            model_name='chatmessage',
            name='is_voice',
            field=models.BooleanField(default=False, verbose_name='Message vocal'),
        ),
        migrations.AddField(
            model_name='chatmessage',
            name='reply_to',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='replies', to='chat.chatmessage', verbose_name='Réponse à'),
        ),
    ]
