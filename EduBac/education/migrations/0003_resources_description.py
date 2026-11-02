from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('education', '0002_lesson_faq_lesson_summary'),
    ]

    operations = [
        migrations.AddField(
            model_name='resources',
            name='description',
            field=models.TextField(
                blank=True,
                default='',
                verbose_name='Description',
            ),
        ),
    ]
