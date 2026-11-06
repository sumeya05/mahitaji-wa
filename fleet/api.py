"""
JSON API for the Mahitaji Fleet mobile app, at /api/v1/fleet/.

Authentication:
- Register: POST /api/v1/fleet/auth/register/
- Login:    POST /api/v1/fleet/auth/login/
- Logout:   POST /api/v1/fleet/auth/logout/
- Me:       GET  /api/v1/fleet/me/

Anyone can register through the Fleet app, without a website account.
A new account can do nothing until the office approves it in the admin
(Fleet -> Access requests -> Approve); then it signs in like everyone else.
"""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q

from rest_framework import status as http
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import ValidationError
from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveUpdateAPIView,
)
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import APIView, exception_handler

from core.models import CustomerProfile
from core.views.auth import SignInRefused, check_sign_in

from .models import AccessRequest, Area, Company, Employee, Route, Vehicle
from .serializers import (
    AreaSerializer,
    AreaWriteSerializer,
    CompanySerializer,
    CustomerSerializer,
    CustomerWriteSerializer,
    EmployeeSerializer,
    EmployeeWriteSerializer,
    RouteSerializer,
    RouteWriteSerializer,
    VehicleSerializer,
    VehicleWriteSerializer,
)


User = get_user_model()


# ===========================================================================
# RESOURCES / PERMISSIONS
# ===========================================================================

RESOURCES = {
    'companies': 'fleet.%s_company',
    'employees': 'fleet.%s_employee',
    'routes': 'fleet.%s_route',
    'areas': 'fleet.%s_area',
    'vehicles': 'fleet.%s_vehicle',
    'customers': 'core.%s_customerprofile',
}


def can(user, resource, action):
    """
    Check whether the user has permission for a resource.
    """

    perm = RESOURCES[resource]

    if action == 'view':
        return (
            user.has_perm(perm % 'view')
            or user.has_perm(perm % 'change')
        )

    return user.has_perm(perm % action)


def permissions_json(user):
    """
    Return permissions available to the mobile app.
    """

    return {
        resource: {
            action: can(user, resource, action)
            for action in ('view', 'add', 'change')
        }
        for resource in RESOURCES
    }


def has_fleet_access(user):
    """
    A user has Fleet access if they have permission to view
    at least one Fleet resource.

    Customer permissions are intentionally excluded because
    CustomerProfile belongs to the website/core side.
    """

    return any(
        can(user, resource, 'view')
        for resource in (
            'companies',
            'employees',
            'routes',
            'areas',
            'vehicles',
        )
    )


def me_json(user):
    """
    Return logged-in user information.
    """

    return {
        'id': user.id,
        'username': user.username,
        'name': user.get_full_name() or user.username,
        'email': user.email,
        'permissions': permissions_json(user),

        'choices': {
            'roles': [
                {
                    'value': value,
                    'label': label,
                }
                for value, label in Employee.ROLE_CHOICES
            ],

            'vehicle_types': [
                {
                    'value': value,
                    'label': label,
                }
                for value, label in Vehicle.TYPE_CHOICES
            ],
        },
    }


# ===========================================================================
# ERROR HANDLING
# ===========================================================================

def fleet_exception_handler(exc, context):
    """
    Return API errors in a consistent format.
    """

    response = exception_handler(exc, context)

    if response is None:
        return None

    if isinstance(exc, ValidationError) and isinstance(
        response.data,
        dict
    ):

        errors = {
            field: [
                str(message)
                for message in (
                    messages
                    if isinstance(messages, list)
                    else [messages]
                )
            ]
            for field, messages in response.data.items()
        }

        general = errors.pop(
            api_settings.NON_FIELD_ERRORS_KEY,
            None,
        )

        response.data = {
            'error': (
                general[0]
                if general
                else 'Please fix the highlighted fields.'
            ),
            'errors': errors,
        }

    else:

        detail = (
            response.data.get('detail')
            if isinstance(response.data, dict)
            else None
        )

        response.data = {
            'error': str(
                detail
                or 'That did not work. Please try again.'
            ),
            'errors': {},
        }

    return response


# ===========================================================================
# PERMISSIONS
# ===========================================================================

class ResourcePermission(BasePermission):
    """
    GET    -> view
    POST   -> add
    PATCH  -> change
    PUT    -> change
    """

    ACTIONS = {
        'GET': 'view',
        'HEAD': 'view',
        'OPTIONS': 'view',
        'POST': 'add',
        'PUT': 'change',
        'PATCH': 'change',
    }

    def has_permission(self, request, view):

        action = self.ACTIONS.get(request.method)

        return bool(
            request.user
            and request.user.is_authenticated
            and action
            and can(
                request.user,
                view.resource,
                action,
            )
        )


# ===========================================================================
# PAGINATION
# ===========================================================================

class FleetPagination(PageNumberPagination):

    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 500


# ===========================================================================
# GENERIC FLEET VIEWS
# ===========================================================================

class FleetMixin:

    authentication_classes = [
        TokenAuthentication
    ]

    permission_classes = [
        ResourcePermission
    ]

    resource = None
    queryset = None
    write_serializer_class = None

    def get_exception_handler(self):
        return fleet_exception_handler

    def respond_with(
        self,
        instance,
        status=http.HTTP_200_OK,
    ):

        fresh = self.queryset.get(
            pk=instance.pk
        )

        return Response(
            self.serializer_class(
                fresh,
                context=self.get_serializer_context(),
            ).data,
            status=status,
        )


class FleetListView(
    FleetMixin,
    ListCreateAPIView,
):

    pagination_class = FleetPagination

    filters = {}
    missing = {}
    search_fields = []
    active_only = True

    def get_queryset(self):

        queryset = super().get_queryset()

        if self.active_only:
            queryset = queryset.filter(
                is_active=True
            )

        params = self.request.query_params

        for param, lookup in self.filters.items():

            if params.get(param):

                queryset = queryset.filter(
                    **{
                        lookup: params[param]
                    }
                )

        if params.get('missing') in self.missing:

            queryset = queryset.filter(
                **{
                    f"{self.missing[params['missing']]}__isnull": True
                }
            )

        term = params.get(
            'q',
            '',
        ).strip()

        if term and self.search_fields:

            match = Q()

            for field in self.search_fields:

                match |= Q(
                    **{
                        f'{field}__icontains': term
                    }
                )

            queryset = queryset.filter(match)

        return queryset

    def create(
        self,
        request,
        *args,
        **kwargs,
    ):

        serializer = self.write_serializer_class(
            data=request.data,
            context=self.get_serializer_context(),
        )

        serializer.is_valid(
            raise_exception=True
        )

        return self.respond_with(
            serializer.save(),
            status=http.HTTP_201_CREATED,
        )


class FleetDetailView(
    FleetMixin,
    RetrieveUpdateAPIView,
):

    http_method_names = [
        'get',
        'patch',
        'head',
        'options',
    ]

    def update(
        self,
        request,
        *args,
        **kwargs,
    ):

        serializer = self.write_serializer_class(
            self.get_object(),
            data=request.data,
            partial=True,
            context=self.get_serializer_context(),
        )

        serializer.is_valid(
            raise_exception=True
        )

        return self.respond_with(
            serializer.save()
        )


# ===========================================================================
# COMPANIES
# ===========================================================================

class CompanyListView(
    FleetMixin,
    ListAPIView,
):

    resource = 'companies'

    queryset = Company.objects.filter(
        is_active=True
    )

    serializer_class = CompanySerializer

    pagination_class = FleetPagination


# ===========================================================================
# EMPLOYEES
# ===========================================================================

class EmployeeMixin:

    resource = 'employees'

    queryset = (
        Employee.objects
        .select_related('company')
        .prefetch_related(
            'driver_of',
            'turnboy_of',
        )
    )

    serializer_class = EmployeeSerializer

    write_serializer_class = EmployeeWriteSerializer


class EmployeeListView(
    EmployeeMixin,
    FleetListView,
):

    filters = {
        'role': 'role',
        'company': 'company__code',
    }

    search_fields = [
        'employee_code',
        'full_name',
        'phone_number',
    ]


class EmployeeDetailView(
    EmployeeMixin,
    FleetDetailView,
):
    pass


# ===========================================================================
# ROUTES
# ===========================================================================

class RouteMixin:

    resource = 'routes'

    queryset = Route.objects.select_related(
        'company'
    )

    serializer_class = RouteSerializer

    write_serializer_class = RouteWriteSerializer


class RouteListView(
    RouteMixin,
    FleetListView,
):

    filters = {
        'company': 'company__code',
    }

    search_fields = [
        'code',
        'name',
    ]


class RouteDetailView(
    RouteMixin,
    FleetDetailView,
):
    pass


# ===========================================================================
# AREAS
# ===========================================================================

class AreaMixin:

    resource = 'areas'

    queryset = Area.objects.select_related(
        'route',
        'company',
    )

    serializer_class = AreaSerializer

    write_serializer_class = AreaWriteSerializer


class AreaListView(
    AreaMixin,
    FleetListView,
):

    filters = {
        'company': 'company__code',
        'route': 'route__code',
    }

    search_fields = [
        'code',
        'name',
        'town',
        'county',
    ]


class AreaDetailView(
    AreaMixin,
    FleetDetailView,
):
    pass


# ===========================================================================
# VEHICLES
# ===========================================================================

class VehicleMixin:

    resource = 'vehicles'

    queryset = Vehicle.objects.select_related(
        'company',
        'driver',
        'turnboy',
    )

    serializer_class = VehicleSerializer

    write_serializer_class = VehicleWriteSerializer


class VehicleListView(
    VehicleMixin,
    FleetListView,
):

    filters = {
        'company': 'company__code',
        'type': 'vehicle_type',
        'driver': 'driver__employee_code',
    }

    missing = {
        'driver': 'driver',
        'turnboy': 'turnboy',
    }

    search_fields = [
        'registration_number',
        'driver__full_name',
        'turnboy__full_name',
    ]


class VehicleDetailView(
    VehicleMixin,
    FleetDetailView,
):
    pass


# ===========================================================================
# CUSTOMERS
# ===========================================================================

class CustomerMixin:

    resource = 'customers'

    queryset = (
        CustomerProfile.objects
        .select_related(
            'user',
            'area__route',
            'area__company',
        )
        .prefetch_related(
            'addresses'
        )
        .order_by(
            'customer_code'
        )
    )

    serializer_class = CustomerSerializer

    write_serializer_class = CustomerWriteSerializer


class CustomerListView(
    CustomerMixin,
    FleetListView,
):

    active_only = False

    filters = {
        'area': 'area__code',
        'route': 'area__route__code',
        'company': 'area__company__code',
    }

    missing = {
        'area': 'area',
        'location': 'latitude',
    }

    search_fields = [
        'customer_code',
        'business_name',
        'contact_person',
        'phone_number',
    ]


class CustomerDetailView(
    CustomerMixin,
    FleetDetailView,
):
    pass


# ===========================================================================
# FLEET REGISTRATION
# ===========================================================================

class RegisterView(APIView):

    """
    Anyone can create a Mahitaji Fleet account.

    POST /api/v1/fleet/auth/register/

    After registration:
    1. Django user is created, with no permissions.
    2. An access request waits for the office to approve it in the admin.
    3. The app returns to the sign-in screen; signing in works once approved.

    The user is NOT made a superuser.
    The user does NOT need an existing website account.
    """

    authentication_classes = []

    permission_classes = []

    def get_exception_handler(self):
        return fleet_exception_handler

    def post(self, request):

        data = request.data

        username = str(
            data.get('username', '')
        ).strip()

        email = str(
            data.get('email', '')
        ).strip()

        first_name = str(
            data.get('first_name', '')
        ).strip()

        last_name = str(
            data.get('last_name', '')
        ).strip()

        phone = str(
            data.get('phone', '')
        ).strip()

        password = data.get(
            'password'
        )

        password_confirm = data.get(
            'password_confirm'
        )

        errors = {}

        # ---------------------------------------------------------------
        # USERNAME
        # ---------------------------------------------------------------

        if not username:

            errors['username'] = [
                'Username is required.'
            ]

        elif User.objects.filter(
            username__iexact=username
        ).exists():

            errors['username'] = [
                'This username is already in use.'
            ]

        # ---------------------------------------------------------------
        # EMAIL
        # ---------------------------------------------------------------

        if not email:

            errors['email'] = [
                'Email is required.'
            ]

        elif User.objects.filter(
            email__iexact=email
        ).exists():

            errors['email'] = [
                'This email is already in use.'
            ]

        # ---------------------------------------------------------------
        # NAME
        # ---------------------------------------------------------------

        if not first_name:

            errors['first_name'] = [
                'First name is required.'
            ]

        if not last_name:

            errors['last_name'] = [
                'Last name is required.'
            ]

        # ---------------------------------------------------------------
        # PASSWORD
        # ---------------------------------------------------------------

        if not password:

            errors['password'] = [
                'Password is required.'
            ]

        elif len(password) < 8:

            errors['password'] = [
                'Password must be at least 8 characters.'
            ]

        if password != password_confirm:

            errors['password_confirm'] = [
                'Passwords do not match.'
            ]

        # ---------------------------------------------------------------
        # VALIDATION RESPONSE
        # ---------------------------------------------------------------

        if errors:

            return Response(
                {
                    'error': 'Please fix the highlighted fields.',
                    'errors': errors,
                },
                status=http.HTTP_400_BAD_REQUEST,
            )

        # ---------------------------------------------------------------
        # CREATE USER
        # ---------------------------------------------------------------

        with transaction.atomic():

            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            )

            # No permissions yet: the office approves the account in the admin.
            AccessRequest.objects.create(
                user=user,
                phone_number=phone[:15],
            )

        return Response(
            {
                'message': (
                    'Your account has been created. You can sign in '
                    'once the office has approved it.'
                ),
                'username': user.username,
            },
            status=http.HTTP_201_CREATED,
        )


# ===========================================================================
# LOGIN
# ===========================================================================

class LoginView(APIView):

    """
    Login for existing Fleet users.

    Newly registered Fleet users can also log in here.
    """

    authentication_classes = []

    permission_classes = []

    def get_exception_handler(self):
        return fleet_exception_handler

    def post(self, request):

        username = request.data.get(
            'username'
        )

        password = request.data.get(
            'password'
        )

        if not username or not password:

            return Response(
                {
                    'error': 'Username and password are required.',
                    'errors': {},
                },
                status=http.HTTP_400_BAD_REQUEST,
            )

        try:

            user = check_sign_in(
                request,
                username,
                password,
            )

        except SignInRefused as exc:

            return Response(
                {
                    'error': str(exc),
                    'errors': {},
                },
                status=exc.status,
            )

        # ---------------------------------------------------------------
        # CHECK FLEET ACCESS
        # ---------------------------------------------------------------

        if not has_fleet_access(user):

            waiting = AccessRequest.objects.filter(
                user=user,
                approved_at__isnull=True,
            ).exists()

            return Response(
                {
                    'error': (
                        "Your account is waiting for approval. You can "
                        "sign in once the office has approved it."
                        if waiting
                        else "This account doesn't have access to "
                        "Mahitaji Fleet."
                    ),
                    'errors': {},
                },
                status=http.HTTP_403_FORBIDDEN,
            )

        # ---------------------------------------------------------------
        # TOKEN
        # ---------------------------------------------------------------

        token, _ = Token.objects.get_or_create(
            user=user
        )

        return Response(
            {
                'message': 'Signed in successfully.',
                'token': token.key,
                'user': me_json(user),
            },
            status=http.HTTP_200_OK,
        )


# ===========================================================================
# ACCOUNT
# ===========================================================================

class AccountView(APIView):

    authentication_classes = [
        TokenAuthentication
    ]

    permission_classes = [
        IsAuthenticated
    ]

    def get_exception_handler(self):
        return fleet_exception_handler


# ===========================================================================
# ME
# ===========================================================================

class MeView(AccountView):

    def get(self, request):

        return Response(
            me_json(request.user)
        )


# ===========================================================================
# LOGOUT
# ===========================================================================

class LogoutView(AccountView):

    def post(self, request):

        Token.objects.filter(
            user=request.user
        ).delete()

        return Response(
            {
                'ok': True
            }
        )