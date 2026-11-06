"""
Masters for Mahitaji Fleet (the logistics side): companies, employees (drivers and
turnboys), delivery routes and areas, and vehicles.

Delivery customers are the shop's own ``core.CustomerProfile`` records, which carry a
customer code, an area (and through it a route) and a GPS location.

Anyone can create an account in the app, but it can do nothing until the office approves its
``AccessRequest`` in the admin, which puts the person in the Logistics group.
"""
import re

from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Company(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'companies'

    def __str__(self):
        return self.name


class Employee(models.Model):
    """Every employee; drivers and turnboys are told apart by ``role``."""
    ROLE_DRIVER = 'driver'
    ROLE_TURNBOY = 'turnboy'
    ROLE_OTHER = 'other'
    ROLE_CHOICES = [
        (ROLE_DRIVER, 'Driver'),
        (ROLE_TURNBOY, 'Turnboy'),
        (ROLE_OTHER, 'Other staff'),
    ]

    employee_code = models.CharField(max_length=20, unique=True)
    full_name = models.CharField(max_length=150)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_OTHER, db_index=True,
                            help_text='Drivers and turnboys can be mapped to vehicles')
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='employees')
    phone_number = models.CharField(max_length=15, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['full_name']

    def __str__(self):
        return f"{self.full_name} ({self.employee_code})"

    @property
    def vehicle(self):
        """The vehicle this driver or turnboy is mapped to, if any."""
        mapped = self.driver_of.all() if self.role == self.ROLE_DRIVER else self.turnboy_of.all()
        return next(iter(mapped), None)

    def clean(self):
        if not self.pk:
            return
        # A role change must not leave a vehicle with, say, a turnboy in its driver seat.
        mapped = {self.ROLE_DRIVER: self.driver_of, self.ROLE_TURNBOY: self.turnboy_of}
        for role, vehicles in mapped.items():
            vehicle = vehicles.first()
            if self.role != role and vehicle:
                raise ValidationError({'role': f"{self.full_name} is the {dict(self.ROLE_CHOICES)[role].lower()} "
                                               f"of {vehicle}. Unmap them from the vehicle first."})


class Route(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='routes')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['company', 'name'], name='unique_route_name_per_company')]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Area(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    route = models.ForeignKey(Route, on_delete=models.PROTECT, related_name='areas')
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='areas')
    county = models.CharField(max_length=50, blank=True)
    town = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True, help_text='Landmarks or boundaries that help drivers find the area')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['company', 'name'], name='unique_area_name_per_company')]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def clean(self):
        if self.route_id and self.company_id and self.route.company_id != self.company_id:
            raise ValidationError({'route': f"Route {self.route} belongs to {self.route.company}, not this area's company."})


def normalise_registration(value):
    """'  kda  123a ' -> 'KDA 123A', so the same plate cannot be entered twice in different spellings."""
    return re.sub(r'\s+', ' ', (value or '').strip().upper())


class Vehicle(models.Model):
    TYPE_CHOICES = [
        ('lorry', 'Lorry'),
        ('light_truck', 'Light truck (Canter)'),
        ('van', 'Van'),
        ('pickup', 'Pick-up'),
        ('motorbike', 'Motorbike'),
        ('tuk_tuk', 'Tuk-tuk'),
        ('other', 'Other'),
    ]

    registration_number = models.CharField('vehicle number', max_length=15, unique=True, help_text='e.g. KDA 123A')
    vehicle_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    capacity_kg = models.PositiveIntegerField('capacity (kg)', validators=[MinValueValidator(1)],
                                              help_text='Maximum load in kilograms')
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='vehicles')
    driver = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='driver_of')
    turnboy = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='turnboy_of')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['registration_number']
        constraints = [
            # A driver or turnboy is mapped to one vehicle at a time.
            models.UniqueConstraint(fields=['driver'], name='one_vehicle_per_driver'),
            models.UniqueConstraint(fields=['turnboy'], name='one_vehicle_per_turnboy'),
        ]

    def __str__(self):
        return self.registration_number

    def clean(self):
        self.registration_number = normalise_registration(self.registration_number)
        errors = {}
        for field, role in (('driver', Employee.ROLE_DRIVER), ('turnboy', Employee.ROLE_TURNBOY)):
            employee = getattr(self, field)
            if not employee:
                continue
            label = dict(Employee.ROLE_CHOICES)[role]
            if employee.role != role:
                errors[field] = (f"{employee} is recorded as {employee.get_role_display()}, not "
                                 f"{label}. Change their role in the employee master first.")
                continue
            other = Vehicle.objects.filter(**{field: employee}).exclude(pk=self.pk).first()
            if other:
                errors[field] = (f"{employee.full_name} is already the {label.lower()} of {other}. "
                                 f"Take them off that vehicle first.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.registration_number = normalise_registration(self.registration_number)
        super().save(*args, **kwargs)


LOGISTICS_GROUP = 'Logistics'
# What approved staff may do in the app: view, add and edit every master. Companies are set up in the admin.
LOGISTICS_PERMISSIONS = {
    'fleet': ['view_company'] + [f'{action}_{model}' for model in ('employee', 'route', 'area', 'vehicle')
                                 for action in ('view', 'add', 'change')],
    'core': ['view_customerprofile', 'add_customerprofile', 'change_customerprofile'],
}


def logistics_group():
    """The group approved app users join; made with LOGISTICS_PERMISSIONS the first time it is needed."""
    group, created = Group.objects.get_or_create(name=LOGISTICS_GROUP)
    if created:
        wanted = Q()
        for app_label, codenames in LOGISTICS_PERMISSIONS.items():
            wanted |= Q(content_type__app_label=app_label, codename__in=codenames)
        group.permissions.set(Permission.objects.filter(wanted))
    return group


class AccessRequest(models.Model):
    """An account created in the app, waiting for the office to let it in."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='fleet_access_request')
    phone_number = models.CharField(max_length=15, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        return self.user.get_full_name() or self.user.username

    def approve(self, by):
        self.user.groups.add(logistics_group())
        self.approved_at, self.approved_by = timezone.now(), by
        self.save(update_fields=['approved_at', 'approved_by'])
