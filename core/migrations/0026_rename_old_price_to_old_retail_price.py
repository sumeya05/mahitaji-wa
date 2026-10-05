"""
``Product.old_price`` is the previous *retail* price (its wholesale twin is
``old_wholesale_price``), so the field is now called ``old_retail_price``. The database
column keeps its name: nothing changes on disk, and the sibling project that shares the
database keeps working.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0025_backfill_payments_and_vat'),
    ]

    operations = [
        # Only Django's view of the model changes; the table is untouched.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameField(model_name='product', old_name='old_price', new_name='old_retail_price'),
                migrations.AlterField(
                    model_name='product',
                    name='old_retail_price',
                    field=models.DecimalField(
                        blank=True, db_column='old_price', decimal_places=2, max_digits=12, null=True,
                        help_text='Previous retail price; when higher than the retail price the product is a retail offer.',
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
