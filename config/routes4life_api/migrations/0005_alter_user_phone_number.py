# Generated by Django 4.0.3 on 2022-04-19 13:20

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('routes4life_api', '0004_alter_user_phone_number'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='phone_number',
            field=models.CharField(blank=True, default='+000000000', max_length=16, verbose_name='phone number'),
        ),
    ]