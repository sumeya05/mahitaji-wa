"""
Tests for the Mahitaji Fleet masters.

    python manage.py test fleet
"""
from django.contrib.admin.sites import site
from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.authtoken.models import Token
from tablib import Dataset

from core.models import Address, CustomerProfile
from core.resources import CustomerResource

from .models import AccessRequest, Area, Company, Employee, Route, Vehicle
from .resources import EmployeeResource, VehicleResource


def make_masters(test):
    """One company with a driver, a turnboy, a route, an area and a vehicle, stored on the test case."""
    test.company = Company.objects.create(code='MEL', name='Mahitaji Enterprises Ltd')
    test.driver = Employee.objects.create(employee_code='EMP001', full_name='John Kamau', role=Employee.ROLE_DRIVER,
                                          company=test.company, phone_number='254711000001')
    test.turnboy = Employee.objects.create(employee_code='EMP002', full_name='Peter Otieno',
                                           role=Employee.ROLE_TURNBOY, company=test.company)
    test.route = Route.objects.create(code='R01', name='Thika Road', company=test.company)
    test.area = Area.objects.create(code='KSR', name='Kasarani', route=test.route, company=test.company,
                                    county='Nairobi', town='Kasarani')
    test.vehicle = Vehicle.objects.create(registration_number='KDA 123A', vehicle_type='light_truck', capacity_kg=3000,
                                          company=test.company, driver=test.driver, turnboy=test.turnboy)


class VehicleTests(TestCase):
    def setUp(self):
        make_masters(self)

    def test_registration_number_is_normalised(self):
        vehicle = Vehicle.objects.create(registration_number='  kbz  456b ', vehicle_type='van', capacity_kg=1000,
                                         company=self.company)
        self.assertEqual(vehicle.registration_number, 'KBZ 456B')
        duplicate = Vehicle(registration_number='kbz 456B', vehicle_type='van', capacity_kg=1000, company=self.company)
        with self.assertRaises(ValidationError) as caught:
            duplicate.full_clean()
        self.assertIn('registration_number', caught.exception.message_dict)

    def test_driver_and_turnboy_must_have_the_matching_role(self):
        vehicle = Vehicle(registration_number='KCC 111C', vehicle_type='van', capacity_kg=800, company=self.company,
                          driver=Employee.objects.create(employee_code='EMP003', full_name='Clerk',
                                                         company=self.company),
                          turnboy=self.driver)
        with self.assertRaises(ValidationError) as caught:
            vehicle.clean()
        self.assertEqual(set(caught.exception.message_dict), {'driver', 'turnboy'})

    def test_an_employee_is_mapped_to_one_vehicle_at_a_time(self):
        second = Vehicle(registration_number='KCD 222D', vehicle_type='van', capacity_kg=800, company=self.company,
                         driver=self.driver)
        with self.assertRaises(ValidationError) as caught:
            second.full_clean()
        self.assertEqual(caught.exception.message_dict['driver'],
                         ['John Kamau is already the driver of KDA 123A. Take them off that vehicle first.'])
        self.vehicle.full_clean()  # the vehicle they are on is still valid

    def test_role_cannot_change_while_mapped(self):
        self.driver.role = Employee.ROLE_TURNBOY
        with self.assertRaises(ValidationError) as caught:
            self.driver.full_clean()
        self.assertIn('KDA 123A', str(caught.exception))
        self.vehicle.driver = None
        self.vehicle.save()
        self.driver.full_clean()  # unmapped: the change is allowed

    def test_employee_knows_its_vehicle(self):
        self.assertEqual(self.driver.vehicle, self.vehicle)
        self.assertEqual(self.turnboy.vehicle, self.vehicle)
        spare = Employee.objects.create(employee_code='EMP004', full_name='Spare Driver', role=Employee.ROLE_DRIVER,
                                        company=self.company)
        self.assertIsNone(spare.vehicle)


class AreaTests(TestCase):
    def setUp(self):
        make_masters(self)

    def test_route_must_belong_to_the_area_company(self):
        other = Company.objects.create(code='MLL', name='Mahitaji Logistics Ltd')
        area = Area(code='RSB', name='Roysambu', route=self.route, company=other)
        with self.assertRaises(ValidationError) as caught:
            area.full_clean()
        self.assertIn('route', caught.exception.message_dict)


class CustomerMasterTests(TestCase):
    def setUp(self):
        make_masters(self)

    def test_customer_without_login_gets_a_code(self):
        customer = CustomerProfile.objects.create(business_name='Mama Njeri Shop', phone_number='254722000000',
                                                  area=self.area)
        customer.refresh_from_db()
        self.assertEqual(customer.customer_code, f'MC{customer.pk:05d}')
        self.assertEqual(customer.display_name, 'Mama Njeri Shop')
        self.assertEqual(customer.route, self.route)
        address = Address.objects.create(customer=customer, physical_address='Kasarani Mwiki Rd')
        self.assertEqual(str(address), 'Delivery Address - Mama Njeri Shop')

    def test_given_code_is_kept(self):
        customer = CustomerProfile.objects.create(business_name='Duka', phone_number='1', customer_code='C-77')
        customer.refresh_from_db()
        self.assertEqual(customer.customer_code, 'C-77')

    def test_shop_accounts_get_codes_too(self):
        user = User.objects.create_user('jane', 'jane@example.com', 'x')
        profile = CustomerProfile.objects.create(user=user, phone_number='254712345678')
        self.assertTrue(profile.customer_code.startswith('MC'))
        self.assertEqual(profile.display_name, 'jane')

    def test_customer_without_login_needs_a_name(self):
        with self.assertRaises(ValidationError) as caught:
            CustomerProfile(phone_number='254722000000').full_clean()
        self.assertIn('business_name', caught.exception.message_dict)

    def test_location_needs_both_coordinates(self):
        with self.assertRaises(ValidationError):
            CustomerProfile(business_name='Duka', phone_number='1', latitude='-1.2').full_clean()
        CustomerProfile(business_name='Duka', phone_number='1', latitude='-1.218', longitude='36.889').full_clean()


class ImportTests(TestCase):
    def setUp(self):
        make_masters(self)

    def run_import(self, resource, headers, *rows):
        result = resource.import_data(Dataset(*rows, headers=headers), dry_run=False)
        errors = [str(e.error) for e in result.base_errors] + [
            str(error) for _, row_errors in result.row_errors() for error in row_errors]
        invalid = [str(row.error) for row in result.invalid_rows]
        return errors + invalid

    def test_employees_by_role_label_and_company_code(self):
        problems = self.run_import(EmployeeResource(), ['employee_code', 'full_name', 'role', 'company'],
                                   ('EMP010', 'Ali Hassan', 'Driver', 'MEL'), ('EMP011', 'Sam Mwangi', 'turnboy', 'MEL'))
        self.assertEqual(problems, [])
        self.assertEqual(Employee.objects.get(employee_code='EMP010').role, Employee.ROLE_DRIVER)
        self.assertEqual(Employee.objects.get(employee_code='EMP011').role, Employee.ROLE_TURNBOY)

    def test_vehicles_map_crew_by_employee_code(self):
        Employee.objects.create(employee_code='EMP020', full_name='Grace Wanjiru', role=Employee.ROLE_DRIVER,
                                company=self.company)
        headers = ['registration_number', 'vehicle_type', 'capacity_kg', 'company', 'driver', 'turnboy']
        problems = self.run_import(VehicleResource(), headers, ('kbx 900z', 'Lorry', '7000', 'MEL', 'EMP020', ''))
        self.assertEqual(problems, [])
        vehicle = Vehicle.objects.get(registration_number='KBX 900Z')
        self.assertEqual((vehicle.vehicle_type, vehicle.driver.employee_code, vehicle.turnboy), ('lorry', 'EMP020', None))
        # The same plate typed differently updates the vehicle instead of adding a second one.
        self.assertEqual(self.run_import(VehicleResource(), headers, ('KBX  900Z', 'lorry', '8000', 'MEL', 'EMP020', '')), [])
        self.assertEqual(Vehicle.objects.get(registration_number='KBX 900Z').capacity_kg, 8000)

    def test_vehicle_row_with_a_turnboy_as_driver_is_rejected(self):
        headers = ['registration_number', 'vehicle_type', 'capacity_kg', 'company', 'driver']
        problems = self.run_import(VehicleResource(), headers, ('KCE 333E', 'van', '900', 'MEL', 'EMP002'))
        self.assertTrue(problems)
        self.assertFalse(Vehicle.objects.filter(registration_number='KCE 333E').exists())

    def test_customers_with_area_and_address(self):
        headers = ['customer_code', 'business_name', 'contact_person', 'phone_number', 'area', 'latitude', 'longitude',
                   'address', 'city']
        problems = self.run_import(CustomerResource(), headers,
                                   ('', 'Kioski ya Baraka', 'Baraka', '254733000000', 'KSR', '-1.218', '36.889',
                                    'Mwiki Rd, next to the church', 'Nairobi'))
        self.assertEqual(problems, [])
        customer = CustomerProfile.objects.get(business_name='Kioski ya Baraka')
        self.assertIsNone(customer.user)
        self.assertTrue(customer.customer_code.startswith('MC'))
        self.assertEqual(customer.area, self.area)
        self.assertEqual(customer.primary_address.physical_address, 'Mwiki Rd, next to the church')
        # Re-importing by code updates the same customer and its address.
        problems = self.run_import(CustomerResource(), ['customer_code', 'business_name', 'phone_number', 'address'],
                                   (customer.customer_code, 'Kioski ya Baraka', '254733000000', 'Mwiki Rd, shop 4'))
        self.assertEqual(problems, [])
        self.assertEqual(customer.addresses.get().physical_address, 'Mwiki Rd, shop 4')


class FleetAdminTests(TestCase):
    def setUp(self):
        make_masters(self)
        self.admin = User.objects.create_superuser('boss', 'boss@example.com', 'Str0ngPass!42')
        self.client.force_login(self.admin)

    def test_pages_load(self):
        CustomerProfile.objects.create(business_name='Duka', phone_number='1', area=self.area)
        for model in (Company, Employee, Route, Area, Vehicle, CustomerProfile):
            opts = model._meta
            for name, args in (('changelist', []), ('add', []), ('change', [model.objects.first().pk])):
                url = reverse(f'admin:{opts.app_label}_{opts.model_name}_{name}', args=args)
                self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_vehicle_form_offers_only_matching_roles(self):
        request = RequestFactory().get('/')
        request.user = self.admin
        form = site._registry[Vehicle].get_form(request)()
        self.assertEqual(list(form.fields['driver'].queryset), [self.driver])
        self.assertEqual(list(form.fields['turnboy'].queryset), [self.turnboy])


class FleetApiTests(TestCase):
    def setUp(self):
        make_masters(self)
        self.user = User.objects.create_user('logistics', 'ops@example.com', 'Str0ngPass!42')
        self.auth = {'HTTP_AUTHORIZATION': f'Token {Token.objects.create(user=self.user).key}'}

    def grant(self, *codenames):
        self.user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))

    def test_needs_a_token_and_the_view_permission(self):
        url = reverse('fleet:vehicles')
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.get(url, **self.auth).status_code, 403)
        self.grant('view_vehicle')
        response = self.client.get(url, **self.auth)
        self.assertEqual(response.status_code, 200)
        vehicle = response.json()['results'][0]
        self.assertEqual(vehicle['registration_number'], 'KDA 123A')
        self.assertEqual(vehicle['driver']['employee_code'], 'EMP001')
        self.assertEqual(vehicle['turnboy']['full_name'], 'Peter Otieno')
        self.assertEqual(vehicle['company']['code'], 'MEL')

    def test_employees_filter_by_role_and_hide_inactive(self):
        self.grant('view_employee')
        Employee.objects.create(employee_code='EMP009', full_name='Gone', role=Employee.ROLE_DRIVER,
                                company=self.company, is_active=False)
        rows = self.client.get(reverse('fleet:employees'), {'role': 'driver'}, **self.auth).json()['results']
        self.assertEqual([r['employee_code'] for r in rows], ['EMP001'])
        self.assertEqual(rows[0]['vehicle']['registration_number'], 'KDA 123A')

    def test_areas_and_routes(self):
        self.grant('view_area', 'view_route', 'view_company')
        area = self.client.get(reverse('fleet:areas'), {'route': 'R01'}, **self.auth).json()['results'][0]
        self.assertEqual((area['code'], area['route']['code'], area['company']['code']), ('KSR', 'R01', 'MEL'))
        self.assertEqual(self.client.get(reverse('fleet:areas'), {'route': 'NOPE'}, **self.auth).json()['count'], 0)
        self.assertEqual(self.client.get(reverse('fleet:routes'), **self.auth).json()['count'], 1)
        self.assertEqual(self.client.get(reverse('fleet:companies'), **self.auth).json()['count'], 1)

    def test_customers_by_route_in_a_fixed_number_of_queries(self):
        self.grant('view_customerprofile')
        for n in range(5):
            customer = CustomerProfile.objects.create(business_name=f'Shop {n}', phone_number='1', area=self.area,
                                                      latitude='-1.218', longitude='36.889')
            Address.objects.create(customer=customer, physical_address=f'Plot {n}')
        CustomerProfile.objects.create(business_name='Elsewhere', phone_number='2')
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('fleet:customers'), {'route': 'R01'}, **self.auth)
        self.assertLessEqual(len(queries), 6)  # token, permissions, count, page, addresses
        body = response.json()
        self.assertEqual(body['count'], 5)
        first = body['results'][0]
        self.assertEqual(first['area']['code'], 'KSR')
        self.assertEqual(first['route']['name'], 'Thika Road')
        self.assertEqual(first['address']['physical_address'], 'Plot 0')
        self.assertEqual(first['latitude'], -1.218)
        found = self.client.get(reverse('fleet:customers'), {'q': 'elsewhere'}, **self.auth).json()
        self.assertEqual(found['results'][0]['area'], None)


class FleetAppTests(TestCase):
    """What the Mahitaji Fleet app does: sign in, then add and edit masters."""

    def setUp(self):
        make_masters(self)
        self.user = User.objects.create_user('ops', 'ops@example.com', 'Str0ngPass!42', first_name='Olive')
        self.auth = {'HTTP_AUTHORIZATION': f'Token {Token.objects.create(user=self.user).key}'}

    def grant(self, *codenames):
        self.user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))

    def send(self, method, name, data, pk=None):
        url = reverse(f'fleet:{name}', args=[pk] if pk else [])
        return getattr(self.client, method)(url, data, content_type='application/json', **self.auth)

    def test_sign_in_needs_fleet_access(self):
        url = reverse('fleet:login')
        refused = self.client.post(url, {'username': 'ops@example.com', 'password': 'Str0ngPass!42'})
        self.assertEqual(refused.status_code, 403)
        self.assertIn("doesn't have access", refused.json()['error'])
        self.grant('view_vehicle', 'change_vehicle', 'view_customerprofile', 'add_customerprofile')
        signed_in = self.client.post(url, {'username': 'ops@example.com', 'password': 'Str0ngPass!42'}).json()
        self.assertTrue(signed_in['token'])
        self.assertEqual(signed_in['user']['name'], 'Olive')
        perms = signed_in['user']['permissions']
        self.assertEqual(perms['vehicles'], {'view': True, 'add': False, 'change': True})
        self.assertEqual(perms['customers'], {'view': True, 'add': True, 'change': False})
        self.assertFalse(perms['employees']['view'])
        self.assertIn({'value': 'turnboy', 'label': 'Turnboy'}, signed_in['user']['choices']['roles'])

    def test_wrong_password(self):
        response = self.client.post(reverse('fleet:login'), {'username': 'ops', 'password': 'nope'})
        self.assertEqual(response.status_code, 400)
        self.assertIn("couldn't sign you in", response.json()['error'])

    def test_view_only_cannot_add_or_edit(self):
        self.grant('view_vehicle')
        self.assertEqual(self.send('post', 'vehicles', {'registration_number': 'KXX 1X'}).status_code, 403)
        self.assertEqual(self.send('patch', 'vehicle', {'capacity_kg': 1}, pk=self.vehicle.pk).status_code, 403)

    def test_add_vehicle_checks_roles_like_the_admin(self):
        self.grant('add_vehicle')
        data = {'registration_number': 'kbb 777b', 'vehicle_type': 'van', 'capacity_kg': 1200,
                'company': self.company.pk, 'driver': self.turnboy.pk}
        refused = self.send('post', 'vehicles', data)
        self.assertEqual(refused.status_code, 400)
        self.assertIn('not Driver', refused.json()['errors']['driver'][0])
        spare = Employee.objects.create(employee_code='EMP005', full_name='Spare', role=Employee.ROLE_DRIVER,
                                        company=self.company)
        added = self.send('post', 'vehicles', {**data, 'driver': spare.pk})
        self.assertEqual(added.status_code, 201, added.json())
        self.assertEqual(added.json()['registration_number'], 'KBB 777B')
        self.assertEqual(added.json()['driver']['full_name'], 'Spare')
        taken = self.send('post', 'vehicles', {**data, 'registration_number': 'KBB  777B', 'driver': None})
        self.assertIn('registration_number', taken.json()['errors'])

    def test_edit_keeps_unique_fields_and_reports_errors(self):
        self.grant('change_employee', 'change_vehicle')
        # Saving a record with its own unique code must not count as a duplicate of itself.
        edited = self.send('patch', 'employee', {'full_name': 'John K. Kamau', 'employee_code': 'EMP001'}, pk=self.driver.pk)
        self.assertEqual(edited.status_code, 200, edited.json())
        self.assertEqual(edited.json()['full_name'], 'John K. Kamau')
        refused = self.send('patch', 'employee', {'role': 'turnboy'}, pk=self.driver.pk)
        self.assertEqual(refused.status_code, 400)
        self.assertIn('Unmap them', refused.json()['errors']['role'][0])
        self.driver.refresh_from_db()
        self.assertEqual(self.driver.role, Employee.ROLE_DRIVER)
        # Unmap, then the change goes through.
        self.assertEqual(self.send('patch', 'vehicle', {'driver': None}, pk=self.vehicle.pk).json()['driver'], None)
        self.assertEqual(self.send('patch', 'employee', {'role': 'turnboy'}, pk=self.driver.pk).status_code, 200)

    def test_deactivated_records_leave_lists_but_can_be_opened(self):
        self.grant('change_vehicle')
        self.send('patch', 'vehicle', {'is_active': False}, pk=self.vehicle.pk)
        self.assertEqual(self.client.get(reverse('fleet:vehicles'), **self.auth).json()['count'], 0)
        self.assertEqual(self.client.get(reverse('fleet:vehicle', args=[self.vehicle.pk]), **self.auth).status_code, 200)

    def test_area_route_must_match_company(self):
        self.grant('add_area')
        other = Company.objects.create(code='MLL', name='Mahitaji Logistics Ltd')
        refused = self.send('post', 'areas', {'code': 'RSB', 'name': 'Roysambu', 'route': self.route.pk,
                                              'company': other.pk})
        self.assertIn('route', refused.json()['errors'])
        added = self.send('post', 'areas', {'code': 'RSB', 'name': 'Roysambu', 'route': self.route.pk,
                                            'company': self.company.pk, 'county': 'Nairobi'})
        self.assertEqual(added.status_code, 201)
        self.assertEqual(added.json()['route']['code'], 'R01')

    def test_add_and_edit_a_customer_with_location_and_address(self):
        self.grant('add_customerprofile', 'change_customerprofile')
        refused = self.send('post', 'customers', {'phone_number': '0722000000'})
        self.assertIn('business_name', refused.json()['errors'])
        added = self.send('post', 'customers', {
            'business_name': 'Baraka Wholesalers', 'contact_person': 'Baraka', 'phone_number': '0722000000',
            'area': self.area.pk, 'latitude': -1.21834567891, 'longitude': 36.8893456789,
            'address': 'Mwiki Rd, opposite the stage', 'city': 'Nairobi'})
        self.assertEqual(added.status_code, 201, added.json())
        body = added.json()
        self.assertTrue(body['customer_code'].startswith('MC'))
        self.assertFalse(body['has_login'])
        self.assertEqual((body['latitude'], body['longitude']), (-1.218346, 36.889346))
        self.assertEqual(body['route']['code'], 'R01')
        self.assertEqual(body['address']['physical_address'], 'Mwiki Rd, opposite the stage')
        edited = self.send('patch', 'customer', {'address': 'Mwiki Rd, shop 4', 'latitude': None, 'longitude': None},
                           pk=body['id']).json()
        self.assertEqual(edited['address']['physical_address'], 'Mwiki Rd, shop 4')
        self.assertIsNone(edited['latitude'])
        self.assertEqual(CustomerProfile.objects.get(pk=body['id']).addresses.count(), 1)

    def test_sign_out(self):
        self.grant('view_vehicle')
        self.assertEqual(self.client.get(reverse('fleet:me'), **self.auth).status_code, 200)
        self.client.post(reverse('fleet:logout'), **self.auth)
        self.assertEqual(self.client.get(reverse('fleet:me'), **self.auth).status_code, 401)


class FleetRegisterTests(TestCase):
    """Anyone can create a Fleet account in the app; it signs in once the office approves it."""

    details = {'first_name': 'Faith', 'last_name': 'Wanjiru', 'email': 'faith@example.com', 'phone': '254700000001',
               'username': 'faith', 'password': 'Str0ngPass!42', 'password_confirm': 'Str0ngPass!42'}

    def register(self, **changes):
        return self.client.post(reverse('fleet:register'), {**self.details, **changes})

    def approve(self):
        """Approve every waiting account the way the office does: the admin's Approve action."""
        boss = User.objects.create_superuser('boss', 'boss@example.com', 'Str0ngPass!42')
        self.client.force_login(boss)
        url = reverse('admin:fleet_accessrequest_changelist')
        self.assertEqual(self.client.get(url, {'status': 'waiting'}).status_code, 200)
        self.client.post(url, {'action': 'approve', '_selected_action': list(AccessRequest.objects.values_list('pk', flat=True))})
        self.client.logout()

    def test_new_account_waits_for_the_office_to_approve_it(self):
        response = self.register()
        self.assertEqual(response.status_code, 201)
        self.assertNotIn('token', response.json())
        self.assertFalse(Token.objects.exists())
        user = User.objects.get(username='faith')
        self.assertFalse(user.is_superuser or user.is_staff)
        self.assertFalse(user.get_all_permissions())
        self.assertEqual(user.fleet_access_request.phone_number, '254700000001')
        waiting = self.client.post(reverse('fleet:login'), {'username': 'faith', 'password': 'Str0ngPass!42'})
        self.assertEqual(waiting.status_code, 403)
        self.assertIn('waiting for approval', waiting.json()['error'])

        self.approve()
        self.assertEqual(AccessRequest.objects.get().approved_by.username, 'boss')
        signed_in = self.client.post(reverse('fleet:login'), {'username': 'faith', 'password': 'Str0ngPass!42'})
        perms = signed_in.json()['user']['permissions']
        self.assertEqual(perms['vehicles'], {'view': True, 'add': True, 'change': True})
        self.assertEqual(perms['companies'], {'view': True, 'add': False, 'change': False})
        self.assertEqual(perms['customers'], {'view': True, 'add': True, 'change': True})

    def test_signs_in_later_with_username_or_email(self):
        self.register()
        self.approve()
        for login_input in ('faith', 'Faith@Example.com'):
            response = self.client.post(reverse('fleet:login'), {'username': login_input, 'password': 'Str0ngPass!42'})
            self.assertEqual(response.status_code, 200, login_input)

    def test_taken_username_or_email_and_mismatched_passwords_are_refused(self):
        User.objects.create_user('Faith', 'FAITH@example.com', 'Other0ne!23')
        response = self.register(password_confirm='different')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()['errors']), {'username', 'email', 'password_confirm'})
        self.assertEqual(User.objects.count(), 1)

    def test_website_accounts_do_not_get_fleet_access(self):
        User.objects.create_user('shopper', 'shopper@example.com', 'Str0ngPass!42')
        response = self.client.post(reverse('fleet:login'), {'username': 'shopper', 'password': 'Str0ngPass!42'})
        self.assertEqual(response.status_code, 403)
        self.assertIn("doesn't have access", response.json()['error'])


class SeedFleetDemoTests(TestCase):
    def test_refuses_without_debug(self):
        from django.core.management import CommandError, call_command
        with self.assertRaises(CommandError):
            call_command('seed_fleet_demo')

    def test_seeds_once_and_the_demo_user_can_sign_in(self):
        import io
        from django.core.management import call_command
        from django.test import override_settings
        with override_settings(DEBUG=True):
            call_command('seed_fleet_demo', stdout=io.StringIO())
            call_command('seed_fleet_demo', stdout=io.StringIO())  # second run: nothing added
        self.assertEqual(Vehicle.objects.count(), 4)
        self.assertEqual(Vehicle.objects.get(registration_number='KDA 123A').driver.full_name, 'John Kamau')
        self.assertEqual(CustomerProfile.objects.filter(area__route__code='R01').count(), 3)
        signed_in = self.client.post(reverse('fleet:login'), {'username': 'fleet@example.com', 'password': 'Fleet2026!secure'})
        self.assertEqual(signed_in.status_code, 200)
        perms = signed_in.json()['user']['permissions']
        self.assertEqual(perms['customers'], {'view': True, 'add': True, 'change': True})
        self.assertEqual(perms['companies'], {'view': True, 'add': False, 'change': False})


class MissingFilterTests(TestCase):
    """The app's "needs attention" counts: what still has to be filled in."""

    def setUp(self):
        make_masters(self)
        user = User.objects.create_user('ops', 'ops@example.com', 'x')
        user.user_permissions.add(*Permission.objects.filter(codename__in=['view_vehicle', 'view_customerprofile']))
        self.auth = {'HTTP_AUTHORIZATION': f'Token {Token.objects.create(user=user).key}'}

    def count(self, name, missing):
        return self.client.get(reverse(f'fleet:{name}'), {'missing': missing}, **self.auth).json()['count']

    def test_vehicles_without_crew(self):
        Vehicle.objects.create(registration_number='KMEA 1A', vehicle_type='motorbike', capacity_kg=150, company=self.company)
        self.assertEqual((self.count('vehicles', 'driver'), self.count('vehicles', 'turnboy')), (1, 1))
        self.assertEqual(self.count('vehicles', 'nonsense'), 2)  # an unknown value filters nothing

    def test_customers_without_area_or_location(self):
        CustomerProfile.objects.create(business_name='Mapped', phone_number='1', area=self.area, latitude='-1.2', longitude='36.8')
        CustomerProfile.objects.create(business_name='Unmapped', phone_number='2')
        self.assertEqual((self.count('customers', 'area'), self.count('customers', 'location')), (1, 1))
