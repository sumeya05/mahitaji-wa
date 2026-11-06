from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.settings import api_settings

from core.models import Address, CustomerProfile

from .models import Area, Company, Employee, Route, Vehicle


class CodeNameSerializer(serializers.Serializer):
    """A related master shown as {id, code, name}."""
    id = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ['id', 'code', 'name']


class EmployeeSerializer(serializers.ModelSerializer):
    company = CodeNameSerializer()
    role_display = serializers.CharField(source='get_role_display')
    vehicle = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = ['id', 'employee_code', 'full_name', 'role', 'role_display', 'company', 'phone_number', 'vehicle',
                  'is_active']

    def get_vehicle(self, employee):
        vehicle = employee.vehicle
        return {'id': vehicle.id, 'registration_number': vehicle.registration_number} if vehicle else None


class RouteSerializer(serializers.ModelSerializer):
    company = CodeNameSerializer()

    class Meta:
        model = Route
        fields = ['id', 'code', 'name', 'company', 'is_active']


class AreaSerializer(serializers.ModelSerializer):
    route = CodeNameSerializer()
    company = CodeNameSerializer()

    class Meta:
        model = Area
        fields = ['id', 'code', 'name', 'route', 'company', 'county', 'town', 'description', 'is_active']


class CrewMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ['id', 'employee_code', 'full_name', 'phone_number']


class VehicleSerializer(serializers.ModelSerializer):
    vehicle_type_display = serializers.CharField(source='get_vehicle_type_display')
    company = CodeNameSerializer()
    driver = CrewMemberSerializer(allow_null=True)
    turnboy = CrewMemberSerializer(allow_null=True)

    class Meta:
        model = Vehicle
        fields = ['id', 'registration_number', 'vehicle_type', 'vehicle_type_display', 'capacity_kg', 'company',
                  'driver', 'turnboy', 'is_active']


class CustomerSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='display_name')
    email = serializers.SerializerMethodField()
    has_login = serializers.SerializerMethodField()
    address = serializers.SerializerMethodField()
    area = CodeNameSerializer(allow_null=True)
    route = CodeNameSerializer(allow_null=True)
    latitude = serializers.FloatField(allow_null=True)
    longitude = serializers.FloatField(allow_null=True)

    class Meta:
        model = CustomerProfile
        fields = ['id', 'customer_code', 'name', 'business_name', 'contact_person', 'phone_number', 'email', 'has_login',
                  'address', 'area', 'route', 'latitude', 'longitude']

    def get_has_login(self, customer):
        return customer.user_id is not None

    def get_email(self, customer):
        return customer.user.email if customer.user else ''

    def get_address(self, customer):
        # From the prefetched addresses (primary first, see Address.Meta.ordering), not a query per customer.
        address = next(iter(customer.addresses.all()), None)
        return {'physical_address': address.physical_address, 'city': address.city} if address else None


# ---------------------------------------------------------------------------
# Writing (add / edit from the app). Related masters are sent as ids; the model's own
# clean() runs too, so the app gets the same checks as the admin (roles, company match...).
# ---------------------------------------------------------------------------
class ModelCleanSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        attrs = super().validate(attrs)
        model = self.Meta.model
        model_fields = {f.name for f in model._meta.fields}
        # Check a copy, so a rejected edit leaves the stored record untouched.
        instance = model(**{f.attname: getattr(self.instance, f.attname) for f in model._meta.fields}) if self.instance else model()
        if self.instance:
            instance._state.adding = False  # an existing row: unique checks must not count it against itself
            instance._state.db = self.instance._state.db
        for name, value in attrs.items():
            if name in model_fields:
                setattr(instance, name, value)
        try:
            instance.full_clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError({
                (api_settings.NON_FIELD_ERRORS_KEY if field == '__all__' else field): messages
                for field, messages in exc.message_dict.items()
            })
        return attrs


class EmployeeWriteSerializer(ModelCleanSerializer):
    class Meta:
        model = Employee
        fields = ['employee_code', 'full_name', 'role', 'company', 'phone_number', 'is_active']


class RouteWriteSerializer(ModelCleanSerializer):
    class Meta:
        model = Route
        fields = ['code', 'name', 'company', 'is_active']


class AreaWriteSerializer(ModelCleanSerializer):
    class Meta:
        model = Area
        fields = ['code', 'name', 'route', 'company', 'county', 'town', 'description', 'is_active']


class VehicleWriteSerializer(ModelCleanSerializer):
    class Meta:
        model = Vehicle
        fields = ['registration_number', 'vehicle_type', 'capacity_kg', 'company', 'driver', 'turnboy', 'is_active']


class CoordinateField(serializers.DecimalField):
    """GPS degrees. Phones report more decimals than the 6 stored (about 10 cm), so round instead of refusing."""

    def __init__(self, **kwargs):
        super().__init__(max_digits=9, decimal_places=6, allow_null=True, required=False, **kwargs)

    def validate_precision(self, value):
        return super().validate_precision(value.quantize(Decimal('0.000001')))


class CustomerWriteSerializer(ModelCleanSerializer):
    """A delivery customer. ``address`` / ``city`` fill the primary delivery address."""
    latitude = CoordinateField()
    longitude = CoordinateField()
    address = serializers.CharField(required=False, allow_blank=True, write_only=True)
    city = serializers.CharField(required=False, allow_blank=True, write_only=True, max_length=100)

    class Meta:
        model = CustomerProfile
        fields = ['customer_code', 'business_name', 'contact_person', 'phone_number', 'area', 'latitude', 'longitude',
                  'address', 'city']

    def save(self, **kwargs):
        physical = (self.validated_data.pop('address', '') or '').strip()
        city = (self.validated_data.pop('city', '') or '').strip() or 'Nairobi'
        customer = super().save(**kwargs)
        if physical:
            address = customer.primary_address
            if address:
                address.physical_address, address.city = physical, city
                address.save()
            else:
                Address.objects.create(customer=customer, physical_address=physical, city=city, is_primary=True)
        return customer
