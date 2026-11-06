"""
CustomerProfile becomes the customer master for Mahitaji Fleet: a customer code, a delivery
area (and through it a route) and a GPS location; staff can add customers without a shop login.
Existing customers get codes built from their id, the same way new ones do (MC00042).
"""
import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def assign_customer_codes(apps, schema_editor):
    CustomerProfile = apps.get_model('core', 'CustomerProfile')
    for profile in CustomerProfile.objects.filter(customer_code__isnull=True).only('pk').iterator():
        CustomerProfile.objects.filter(pk=profile.pk).update(customer_code=f"MC{profile.pk:05d}")


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0027_hash_chat_session_keys'),
        ('fleet', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='customerprofile',
            name='area',
            field=models.ForeignKey(blank=True, help_text='Delivery area; the route comes from the area', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='customers', to='fleet.area'),
        ),
        migrations.AddField(
            model_name='customerprofile',
            name='customer_code',
            field=models.CharField(blank=True, help_text='Left blank, a code like MC00042 is assigned', max_length=20, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='customerprofile',
            name='latitude',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True, validators=[django.core.validators.MinValueValidator(-90), django.core.validators.MaxValueValidator(90)]),
        ),
        migrations.AddField(
            model_name='customerprofile',
            name='longitude',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True, validators=[django.core.validators.MinValueValidator(-180), django.core.validators.MaxValueValidator(180)]),
        ),
        migrations.AlterField(
            model_name='customerprofile',
            name='user',
            field=models.OneToOneField(blank=True, help_text='Shop login, if the customer has one', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='customerprofile', to=settings.AUTH_USER_MODEL),
        ),
        migrations.RunPython(assign_customer_codes, migrations.RunPython.noop),
    ]
