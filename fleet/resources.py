"""
Import / export for the fleet masters. Related records are matched by their codes, so a
CSV says ``company = MEL`` or ``driver = EMP014`` instead of database ids.
"""
from import_export import fields, resources
from import_export.widgets import ForeignKeyWidget

from .models import Area, Company, Employee, Route, Vehicle, normalise_registration


def choice_value(value, choices):
    """Accept a choice by its stored value or its label, in any case: 'Turnboy' -> 'turnboy'."""
    text = (value or '').strip().lower()
    for stored, label in choices:
        if text in (stored, label.lower()):
            return stored
    return text  # unknown: left for model validation to reject with the list of valid choices


def company_field():
    return fields.Field(column_name='company', attribute='company', widget=ForeignKeyWidget(Company, 'code'))


class FleetResource(resources.ModelResource):
    class Meta:
        clean_model_instances = True  # run the model's own checks (roles, company match) on every row
        skip_unchanged = True
        report_skipped = True


class CompanyResource(FleetResource):
    class Meta(FleetResource.Meta):
        model = Company
        import_id_fields = ('code',)
        fields = ('code', 'name', 'is_active')


class EmployeeResource(FleetResource):
    company = company_field()

    class Meta(FleetResource.Meta):
        model = Employee
        import_id_fields = ('employee_code',)
        fields = ('employee_code', 'full_name', 'role', 'company', 'phone_number', 'is_active')

    def before_import_row(self, row, **kwargs):
        if 'role' in row:
            row['role'] = choice_value(row['role'], Employee.ROLE_CHOICES)


class RouteResource(FleetResource):
    company = company_field()

    class Meta(FleetResource.Meta):
        model = Route
        import_id_fields = ('code',)
        fields = ('code', 'name', 'company', 'is_active')


class AreaResource(FleetResource):
    route = fields.Field(column_name='route', attribute='route', widget=ForeignKeyWidget(Route, 'code'))
    company = company_field()

    class Meta(FleetResource.Meta):
        model = Area
        import_id_fields = ('code',)
        fields = ('code', 'name', 'route', 'company', 'county', 'town', 'description', 'is_active')


class VehicleResource(FleetResource):
    company = company_field()
    driver = fields.Field(column_name='driver', attribute='driver', widget=ForeignKeyWidget(Employee, 'employee_code'))
    turnboy = fields.Field(column_name='turnboy', attribute='turnboy', widget=ForeignKeyWidget(Employee, 'employee_code'))

    class Meta(FleetResource.Meta):
        model = Vehicle
        import_id_fields = ('registration_number',)
        fields = ('registration_number', 'vehicle_type', 'capacity_kg', 'company', 'driver', 'turnboy', 'is_active')

    def before_import_row(self, row, **kwargs):
        # Match "kda 123a" in a CSV to the stored "KDA 123A" instead of trying to add it again.
        if 'registration_number' in row:
            row['registration_number'] = normalise_registration(row['registration_number'])
        if 'vehicle_type' in row:
            row['vehicle_type'] = choice_value(row['vehicle_type'], Vehicle.TYPE_CHOICES)
