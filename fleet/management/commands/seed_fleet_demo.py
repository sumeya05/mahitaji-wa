"""
Fill an empty development database with sample Mahitaji Fleet masters, for previewing the
Mahitaji Fleet app locally: a company, drivers and turnboys, three routes with their areas,
vehicles with crews, delivery customers with GPS locations, and a "Logistics" group with a
member who can sign in to the app: fleet@example.com / Fleet2026!secure.

    DEBUG=true USE_SQLITE=true python manage.py seed_fleet_demo

It refuses to run with DEBUG off, and does nothing when fleet data already exists, so it can
be run on every start of the preview and can never put sample data into the real system.
"""
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Address, CustomerProfile
from fleet.models import Area, Company, Employee, Route, Vehicle, logistics_group

DEMO_EMAIL = 'fleet@example.com'
DEMO_PASSWORD = 'Fleet2026!secure'

# code, name, role, phone
EMPLOYEES = [
    ('EMP001', 'John Kamau', Employee.ROLE_DRIVER, '254711000001'),
    ('EMP002', 'Peter Otieno', Employee.ROLE_TURNBOY, '254711000002'),
    ('EMP003', 'Grace Wanjiru', Employee.ROLE_DRIVER, '254711000003'),
    ('EMP004', 'Brian Mutua', Employee.ROLE_TURNBOY, '254711000004'),
    ('EMP005', 'Hassan Ali', Employee.ROLE_DRIVER, '254711000005'),
    ('EMP006', 'Kevin Ochieng', Employee.ROLE_TURNBOY, '254711000006'),
    ('EMP007', 'Mercy Njeri', Employee.ROLE_OTHER, '254711000007'),
]
# route code, route name, [(area code, area name, town)]
ROUTES = [
    ('R01', 'Thika Road', [('KSR', 'Kasarani', 'Kasarani'), ('RSB', 'Roysambu', 'Roysambu'), ('GTH', 'Githurai', 'Githurai 45')]),
    ('R02', 'Mombasa Road', [('IND', 'Industrial Area', 'Nairobi'), ('EMB', 'Embakasi', 'Embakasi'), ('GKB', 'Gikomba', 'Nairobi')]),
    ('R03', 'Westlands', [('WST', 'Westlands', 'Westlands'), ('PKL', 'Parklands', 'Parklands')]),
]
# registration, type, capacity kg, driver code, turnboy code
VEHICLES = [
    ('KDA 123A', 'light_truck', 3000, 'EMP001', 'EMP002'),
    ('KCB 456B', 'lorry', 10000, 'EMP003', 'EMP004'),
    ('KDE 789C', 'van', 1500, 'EMP005', None),
    ('KMEA 321D', 'motorbike', 150, None, None),
]
# name, contact, phone, area code, address, latitude, longitude
CUSTOMERS = [
    ('Baraka Wholesalers', 'Baraka Mwangi', '254722100001', 'KSR', 'Mwiki Road, opposite the stage', '-1.218300', '36.889300'),
    ('Mama Njeri Shop', 'Njeri Kariuki', '254722100002', 'RSB', 'Roysambu, next to TRM', '-1.217900', '36.888100'),
    ('Githurai Mini Mart', 'Samuel Kibet', '254722100003', 'GTH', 'Githurai 45, Kamiti Road', '-1.200700', '36.915700'),
    ('Industrial Area Canteen', 'Faith Atieno', '254722100004', 'IND', 'Enterprise Road', '-1.309700', '36.851200'),
    ('Embakasi Duka', 'Ali Abdi', '254722100005', 'EMB', 'Embakasi Village, shop 12', '-1.322800', '36.894800'),
    ('Westlands Supplies', 'Diana Wambui', '254722100006', 'WST', 'Woodvale Grove', '-1.264800', '36.802900'),
]


class Command(BaseCommand):
    help = "Fill an empty development database with sample Mahitaji Fleet masters (DEBUG only)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_fleet_demo only runs with DEBUG=true: it must never touch the real system.")
        if Company.objects.exists():
            self.stdout.write("Fleet data already exists; seed_fleet_demo left it as it is.")
            return

        with transaction.atomic():
            company = Company.objects.create(code='MEL', name='Mahitaji Enterprises Ltd')
            employees = {
                code: Employee.objects.create(employee_code=code, full_name=name, role=role, company=company, phone_number=phone)
                for code, name, role, phone in EMPLOYEES
            }
            areas = {}
            for route_code, route_name, route_areas in ROUTES:
                route = Route.objects.create(code=route_code, name=route_name, company=company)
                for code, name, town in route_areas:
                    areas[code] = Area.objects.create(code=code, name=name, route=route, company=company,
                                                      county='Nairobi', town=town)
            for registration, vehicle_type, capacity, driver, turnboy in VEHICLES:
                Vehicle.objects.create(registration_number=registration, vehicle_type=vehicle_type, capacity_kg=capacity,
                                       company=company, driver=employees.get(driver), turnboy=employees.get(turnboy))
            for name, contact, phone, area, address, latitude, longitude in CUSTOMERS:
                customer = CustomerProfile.objects.create(
                    business_name=name, contact_person=contact, phone_number=phone, area=areas[area],
                    latitude=Decimal(latitude), longitude=Decimal(longitude))
                Address.objects.create(customer=customer, physical_address=address, city='Nairobi', is_primary=True)
            # The shop's sample customer (seed_demo), if present, trades at Gikomba.
            CustomerProfile.objects.filter(user__email__iexact='amina@example.com', area=None).update(area=areas['GKB'])

            user = User.objects.filter(email__iexact=DEMO_EMAIL).first()
            if not user:
                user = User.objects.create_user('fleet-office', email=DEMO_EMAIL, password=DEMO_PASSWORD,
                                                first_name='Faith', last_name='Achieng')
            user.groups.add(logistics_group())

        self.stdout.write(self.style.SUCCESS(
            f"Sample fleet ready: {len(VEHICLES)} vehicles, {len(EMPLOYEES)} employees, {len(areas)} areas, "
            f"{len(CUSTOMERS)} customers. Sign in to the app as {DEMO_EMAIL} / {DEMO_PASSWORD}."))
