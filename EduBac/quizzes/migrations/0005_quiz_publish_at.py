from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('quizzes', '0004_attempt_teacher_comment'),
    ]

    operations = [
        migrations.AddField(
            model_name='quiz',
            name='publish_at',
            field=models.DateTimeField(blank=True, help_text='Si défini, le quiz passera en publié à cette date.', null=True, verbose_name='Publication programmée'),
        ),
    ]
