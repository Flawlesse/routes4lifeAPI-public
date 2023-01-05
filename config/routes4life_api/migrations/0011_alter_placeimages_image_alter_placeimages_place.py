# Generated by Django 4.0.3 on 2022-06-07 17:00

from django.db import migrations, models
import django.db.models.deletion
import routes4life_api.utils


class Migration(migrations.Migration):

    dependencies = [
        ('routes4life_api', '0010_alter_place_main_image_alter_placerating_place'),
    ]

    operations = [
        migrations.AlterField(
            model_name='placeimages',
            name='image',
            field=models.ImageField(blank=True, null=True, upload_to=routes4life_api.utils.upload_place_secimg_to),
        ),
        migrations.AlterField(
            model_name='placeimages',
            name='place',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='secondary_images', to='routes4life_api.place'),
        ),
    ]