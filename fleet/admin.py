from django.contrib import admin
from django.db.models import Count
from import_export.admin import ImportExportModelAdmin

from .models import AccessRequest, Area, Company, Employee, Route, Vehicle
from .resources import AreaResource, CompanyResource, EmployeeResource, RouteResource, VehicleResource


@admin.register(Company)
class CompanyAdmin(ImportExportModelAdmin):
    resource_class = CompanyResource
    list_display = ['code', 'name', 'is_active']
    list_filter = ['is_active']
    search_fields = ['code', 'name']


@admin.register(Employee)
class EmployeeAdmin(ImportExportModelAdmin):
    resource_class = EmployeeResource
    list_display = ['employee_code', 'full_name', 'role', 'company', 'phone_number', 'mapped_vehicle', 'is_active']
    list_filter = ['role', 'company', 'is_active']
    search_fields = ['employee_code', 'full_name', 'phone_number']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('company').prefetch_related('driver_of', 'turnboy_of')

    @admin.display(description='Vehicle')
    def mapped_vehicle(self, obj):
        return obj.vehicle or '-'


@admin.register(Route)
class RouteAdmin(ImportExportModelAdmin):
    resource_class = RouteResource
    list_display = ['code', 'name', 'company', 'area_count', 'is_active']
    list_filter = ['company', 'is_active']
    search_fields = ['code', 'name']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('company').annotate(num_areas=Count('areas'))

    @admin.display(description='Areas', ordering='num_areas')
    def area_count(self, obj):
        return obj.num_areas


@admin.register(Area)
class AreaAdmin(ImportExportModelAdmin):
    resource_class = AreaResource
    list_display = ['code', 'name', 'route', 'company', 'county', 'town', 'customer_count', 'is_active']
    list_filter = ['company', 'route', 'county', 'is_active']
    search_fields = ['code', 'name', 'town', 'county', 'route__name']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('route', 'company').annotate(num_customers=Count('customers'))

    @admin.display(description='Customers', ordering='num_customers')
    def customer_count(self, obj):
        return obj.num_customers


@admin.register(Vehicle)
class VehicleAdmin(ImportExportModelAdmin):
    resource_class = VehicleResource
    list_display = ['registration_number', 'vehicle_type', 'capacity_kg', 'company', 'driver', 'turnboy', 'is_active']
    list_filter = ['vehicle_type', 'company', 'is_active']
    search_fields = ['registration_number', 'driver__full_name', 'driver__employee_code',
                     'turnboy__full_name', 'turnboy__employee_code']
    list_select_related = ['company', 'driver', 'turnboy']

    # Only drivers are offered as drivers, only turnboys as turnboys.
    ROLE_FOR_FIELD = {'driver': Employee.ROLE_DRIVER, 'turnboy': Employee.ROLE_TURNBOY}

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        role = self.ROLE_FOR_FIELD.get(db_field.name)
        if role:
            kwargs['queryset'] = Employee.objects.filter(role=role).select_related('company')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class AccessStatusFilter(admin.SimpleListFilter):
    title = 'status'
    parameter_name = 'status'

    def lookups(self, request, model_admin):
        return [('waiting', 'Waiting'), ('approved', 'Approved')]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(approved_at__isnull=self.value() == 'waiting')
        return queryset


@admin.register(AccessRequest)
class AccessRequestAdmin(admin.ModelAdmin):
    """Accounts created in the app. Approving one lets the person sign in (Logistics group)."""
    list_display = ['user', 'full_name', 'email', 'phone_number', 'requested_at', 'approved', 'approved_by']
    list_filter = [AccessStatusFilter]
    search_fields = ['user__username', 'user__email', 'user__first_name', 'user__last_name', 'phone_number']
    list_select_related = ['user', 'approved_by']
    readonly_fields = ['user', 'phone_number', 'requested_at', 'approved_at', 'approved_by']
    actions = ['approve']

    def has_add_permission(self, request):
        return False  # requests come from "Create account" in the app

    @admin.display(description='Name')
    def full_name(self, obj):
        return obj.user.get_full_name()

    @admin.display(description='Email')
    def email(self, obj):
        return obj.user.email

    @admin.display(description='Approved', boolean=True, ordering='approved_at')
    def approved(self, obj):
        return obj.approved_at is not None

    @admin.action(description='Approve: let them sign in to Mahitaji Fleet', permissions=['change'])
    def approve(self, request, queryset):
        waiting = list(queryset.filter(approved_at__isnull=True).select_related('user'))
        for access in waiting:
            access.approve(by=request.user)
        self.message_user(request, f"Approved {len(waiting)} account{'s' if len(waiting) != 1 else ''}. "
                                   "They can sign in to the app now.")
