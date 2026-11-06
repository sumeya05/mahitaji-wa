from django.urls import path

from . import api

app_name = 'fleet'

urlpatterns = [
    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    path(
        'auth/register/',
        api.RegisterView.as_view(),
        name='register'
    ),

    path(
        'auth/login/',
        api.LoginView.as_view(),
        name='login'
    ),

    path(
        'auth/logout/',
        api.LogoutView.as_view(),
        name='logout'
    ),

    path(
        'me/',
        api.MeView.as_view(),
        name='me'
    ),

    # ------------------------------------------------------------------
    # Companies
    # ------------------------------------------------------------------
    path(
        'companies/',
        api.CompanyListView.as_view(),
        name='companies'
    ),

    # ------------------------------------------------------------------
    # Employees
    # ------------------------------------------------------------------
    path(
        'employees/',
        api.EmployeeListView.as_view(),
        name='employees'
    ),

    path(
        'employees/<int:pk>/',
        api.EmployeeDetailView.as_view(),
        name='employee'
    ),

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------
    path(
        'routes/',
        api.RouteListView.as_view(),
        name='routes'
    ),

    path(
        'routes/<int:pk>/',
        api.RouteDetailView.as_view(),
        name='route'
    ),

    # ------------------------------------------------------------------
    # Areas
    # ------------------------------------------------------------------
    path(
        'areas/',
        api.AreaListView.as_view(),
        name='areas'
    ),

    path(
        'areas/<int:pk>/',
        api.AreaDetailView.as_view(),
        name='area'
    ),

    # ------------------------------------------------------------------
    # Vehicles
    # ------------------------------------------------------------------
    path(
        'vehicles/',
        api.VehicleListView.as_view(),
        name='vehicles'
    ),

    path(
        'vehicles/<int:pk>/',
        api.VehicleDetailView.as_view(),
        name='vehicle'
    ),

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------
    path(
        'customers/',
        api.CustomerListView.as_view(),
        name='customers'
    ),

    path(
        'customers/<int:pk>/',
        api.CustomerDetailView.as_view(),
        name='customer'
    ),
]