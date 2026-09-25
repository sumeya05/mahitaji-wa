# Generic name: the customer's ID in whichever ERP the shop is synced with.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0021_product_old_wholesale_price'),
    ]

    operations = [
        migrations.RenameField(
            model_name='customerprofile',
            old_name='focus_erp_id',
            new_name='erp_id',
        ),
        migrations.AlterField(
            model_name='customerprofile',
            name='erp_id',
            field=models.CharField(blank=True, max_length=50, null=True, verbose_name='ERP customer ID'),
        ),
    ]
