from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget, Widget

from . import images
from .models import Product, Category, Brand, Supplier, UnitOfMeasure, StockLedger


class ProductImageWidget(Widget):
    """
    The ``image`` column of a product CSV. Accepts a file already uploaded to media/products/
    (``bd001.jpg`` or ``products/bd001.jpg``) or an http(s) URL, which is downloaded and saved
    as products/<item_code>.<ext>. A blank cell leaves the product's current photo alone.
    """

    def clean(self, value, row=None, **kwargs):
        value = (value or '').strip()
        if not value:
            return None
        if value.lower().startswith(('http://', 'https://')):
            data, filename = images.fetch(value)
            code = (row or {}).get('item_code') or ''
            ext = images.image_name(filename).rsplit('.', 1)[1]
            return images.store(f"{code or filename}.{ext}", data)
        name = images.resolve(value)
        if not name:
            raise ValueError(f"image '{value}' is not in media/products/. Upload it first (Products > Upload images) "
                             f"or leave the cell blank to keep the current photo.")
        return name

    def render(self, value, obj=None, **kwargs):
        return value.name if value else ''


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

    image = fields.Field(column_name='image', attribute='image', widget=ProductImageWidget())

    class Meta:
        model = Product
        import_id_fields = ('item_code',)
        exclude = ('id', 'slug', 'last_sync_time', 'average_rating')
        skip_unchanged = True
        report_skipped = True

    def before_import(self, dataset, **kwargs):
        # Older CSVs call the previous retail price "old_price".
        if 'old_price' in dataset.headers and 'old_retail_price' not in dataset.headers:
            dataset.headers = ['old_retail_price' if h == 'old_price' else h for h in dataset.headers]
        return super().before_import(dataset, **kwargs)

    def import_field(self, field, instance, row, is_m2m=False, **kwargs):
        # A blank image cell means "no change", never "remove the photo".
        if field.column_name == 'image' and not (row.get('image') or '').strip():
            return
        super().import_field(field, instance, row, is_m2m, **kwargs)

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