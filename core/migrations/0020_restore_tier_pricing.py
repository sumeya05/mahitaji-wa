"""
Repair migration: bring a database that was migrated by a *different* copy of
this code (the ``pramo`` project shared ``mahitaji_db`` for a while and applied
its own ``0019_order_erpnext_sync_fields`` / ``0020_single_price`` migrations)
back in line with the models in this repository.

On a database that already matches the models (fresh installs, the SQLite
test database) every step is skipped, so the migration is a safe no-op there.
"""
from django.db import migrations, models
from django.db.migrations.recorder import MigrationRecorder

FOREIGN_MIGRATIONS = ('0019_order_erpnext_sync_fields', '0020_single_price')


def _columns(schema_editor, table):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        return {column.name for column in connection.introspection.get_table_description(cursor, table)}


def repair_schema(apps, schema_editor):
    Product = apps.get_model('core', 'Product')
    CustomerProfile = apps.get_model('core', 'CustomerProfile')
    Order = apps.get_model('core', 'Order')

    # --- Product: ``price`` -> ``retail_price``, re-add ``wholesale_price`` ---
    product_columns = _columns(schema_editor, Product._meta.db_table)
    if 'price' in product_columns and 'retail_price' not in product_columns:
        old_field = models.DecimalField(max_digits=12, decimal_places=2, default=0)
        old_field.set_attributes_from_name('price')
        schema_editor.alter_field(Product, old_field, Product._meta.get_field('retail_price'))
    if 'wholesale_price' not in product_columns:
        schema_editor.add_field(Product, Product._meta.get_field('wholesale_price'))

    # --- CustomerProfile: re-add the wholesaler flag ---
    if 'is_wholesaler' not in _columns(schema_editor, CustomerProfile._meta.db_table):
        schema_editor.add_field(CustomerProfile, CustomerProfile._meta.get_field('is_wholesaler'))

    # --- Order: drop columns this code base does not know about (one of them is
    #     NOT NULL without a default, which would break every order insert) ---
    order_columns = _columns(schema_editor, Order._meta.db_table)
    for column in ('erp_sync_error', 'erp_synced_at'):
        if column in order_columns:
            stray = models.TextField(null=True)
            stray.set_attributes_from_name(column)
            schema_editor.remove_field(Order, stray)

    # --- Forget the other project's migration records ---
    MigrationRecorder(schema_editor.connection).migration_qs.filter(
        app='core', name__in=FOREIGN_MIGRATIONS
    ).delete()


class Migration(migrations.Migration):
    # DDL on MySQL cannot be rolled back, so the whole migration runs outside a transaction.
    atomic = False

    dependencies = [
        ('core', '0019_orders_payment_wishlist_contact'),
    ]

    operations = [
        migrations.RunPython(repair_schema, migrations.RunPython.noop),
    ]
