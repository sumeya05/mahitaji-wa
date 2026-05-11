from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from .models import Product, Category, Brand, Supplier, UnitOfMeasure, StockLedger


class CategoryResource(resources.ModelResource):
    class Meta:
        model = Category
        import_id_fields = ('name',)
        exclude = ('id', 'slug', 'image')

class BrandResource(resources.ModelResource):
    class Meta:
        model = Brand
        import_id_fields = ('name',)
        exclude = ('id', 'slug', 'logo')

class SupplierResource(resources.ModelResource):
    class Meta:
        model = Supplier
        # Use erp_id as the unique key to prevent duplicates during import
        import_id_fields = ('erp_id',) 
        fields = ('id', 'name', 'erp_id', 'contact_person', 'email', 'phone_number', 'address')

class ProductResource(resources.ModelResource):
    # Mapping Foreign Keys by Name (so you can type "Grains" in CSV instead of ID 1)
    category = fields.Field(
        column_name='category',
        attribute='category',
        widget=ForeignKeyWidget(Category, 'name'))
    
    brand = fields.Field(
        column_name='brand',
        attribute='brand',
        widget=ForeignKeyWidget(Brand, 'name'))
    
    supplier = fields.Field(
        column_name='supplier',
        attribute='supplier',
        widget=ForeignKeyWidget(Supplier, 'name'))
    
    unit_of_measure = fields.Field(
        column_name='uom',
        attribute='unit_of_measure',
        widget=ForeignKeyWidget(UnitOfMeasure, 'short_name'))

    class Meta:
        model = Product
        import_id_fields = ('item_code',)
        exclude = ('id', 'slug', 'description', 'image', 'last_sync_time', 'average_rating')
        skip_unchanged = True
        report_skipped = True

class StockLedgerResource(resources.ModelResource):
    # Map the product column so you can use 'item_code' in your CSV
    product = fields.Field(
        column_name='item_code',
        attribute='product',
        widget=ForeignKeyWidget(Product, 'item_code'))

    class Meta:
        model = StockLedger
        fields = ('id', 'product', 'transaction_type', 'quantity', 'reference_number')
        # We don't use import_id_fields here because every ledger entry is a NEW record