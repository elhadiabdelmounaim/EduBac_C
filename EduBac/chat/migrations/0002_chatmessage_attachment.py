from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatmessage',
            name='attachment',
            field=models.FileField(blank=True, null=True, upload_to='chat/%Y/%m/', verbose_name='Fichier / image'),
        ),
        migrations.AlterField(
            model_name='chatmessage',
            name='body',
            field=models.TextField(blank=True, verbose_name='Message'),
        ),
    ]
