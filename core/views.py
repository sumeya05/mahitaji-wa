from django.shortcuts import render, redirect
from rest_framework import viewsets, permissions
from django.contrib.auth import logout
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django_daraja.mpesa.core import MpesaClient
import json
from datetime import datetime


# --- Protected Views ---
from django.contrib.auth.decorators import login_required

# Import models and serializers
from .models import (
    Product, Category, Order, CustomerProfile, 
    MpesaTransaction
)
from .serializers import (
    ProductSerializer, CategorySerializer, OrderSerializer
)



from django.shortcuts import render, redirect
from rest_framework import viewsets, permissions
from django.contrib.auth import logout, login, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django_daraja.mpesa.core import MpesaClient
import json
from datetime import datetime





# Import models, serializers, and the RegisterForm we'll create
from .models import (
    Product, Category, Order, CustomerProfile, 
    MpesaTransaction
)
from .serializers import (
    ProductSerializer, CategorySerializer, OrderSerializer
)
from .forms import RegisterForm  # Make sure to create this in core/forms.py

# 1. Template & Auth Views

# 1. Template Views
def home(request):
    return render(request, 'core/home.html')

def retailers(request):
    return render(request, 'core/retailers.html')

def wholesalers(request):
    return render(request, 'core/wholesalers.html') 

def categories(request):
    return render(request, 'core/categories.html')

def brands(request):
    return render(request, 'core/brands.html')

def search(request):
    return render(request, 'core/search.html')

def cart(request):
    return render(request, 'core/cart.html')

def checkout(request):
    return render(request, 'core/checkout.html')


# Auth Views
def login_view(request):
    """Hybrid Login: Handles both AJAX and standard POST"""
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = authenticate(
                username=form.cleaned_data.get('username'),
                password=form.cleaned_data.get('password')
            )
            if user is not None:
                login(request, user)
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({"success": True, "redirect_url": "/dashboard/"})
                return redirect('dashboard')
        
        # If invalid
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": "Invalid username or password."}, status=400)
        messages.error(request, "Invalid username or password.")
    
    return render(request, 'core/login.html', {'form': AuthenticationForm()})

def signup(request):
    """Hybrid Signup: Creates User + CustomerProfile"""
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"success": True, "redirect_url": "/dashboard/"})
            return redirect('dashboard')
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            errors = form.errors.get_json_data()
            return JsonResponse({"success": False, "errors": errors}, status=400)
    
    return render(request, 'core/signup.html', {'form': RegisterForm()})

def logout_view(request):
    logout(request)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({"success": True, "redirect_url": "/"})
    return redirect('home')

# Dashboard views
@login_required
def dashboard(request):
    return render(request, 'core/dashboard.html')

@login_required
def transactions(request):
    return render(request, 'core/transactions.html')

@login_required
def addresses(request):
    return render(request, 'core/addresses.html')

@login_required
def payment_methods(request):
    return render(request, 'core/payment_methods.html')

@login_required
def settings(request):
    return render(request, 'core/settings.html')


# Helpdesk & Informational Views
def pickups(request):
    return render(request, 'core/pickups_deliveries.html')

def payment_info(request):
    return render(request, 'core/payment_info.html')

def returns(request):
    return render(request, 'core/return_policy.html')

def faqs(request):
    return render(request, 'core/faqs.html')

def terms(request):
    return render(request, 'core/terms.html')   

def contact(request):
    return render(request, 'core/contact.html') 

def about(request):
    return render(request, 'core/about.html')

def statement(request):
    return render(request, 'core/statement.html')

def location(request):
    return render(request, 'core/location.html')


# 2. API Endpoints
class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.filter(is_active=True)
    serializer_class = ProductSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        category_slug = self.request.query_params.get('category')
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)
        return queryset

class OrderViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OrderSerializer

    def get_queryset(self):
        return Order.objects.filter(customer__user=self.request.user)

    def perform_create(self, serializer):
        customer = CustomerProfile.objects.get(user=self.request.user)
        serializer.save(customer=customer)


# 3. MPESA
def initiate_stk_push(request):
    if request.method == "POST":
        cl = MpesaClient()
        
        # Current Setup for Trial
        phone_number = '254794076386' 
        account_reference = 'Trial'
        transaction_desc = 'Payment Trial'
        callback_url = 'https://abc6-185-177-124-199.ngrok-free.app/mpesa/callback/'
        
        try:
            # Fetch the latest order to link the transaction
            order_instance = Order.objects.latest('id')
            
            # Use the order's total_amount if available, otherwise default to 1 for trial
            amount = int(order_instance.total_amount) if order_instance.total_amount else 1
            
            response = cl.stk_push(phone_number, amount, account_reference, transaction_desc, callback_url)

            # FIX: Use 'order=' instead of 'order_id=' when passing an object instance
            MpesaTransaction.objects.create(
                order=order_instance,
                checkout_request_id=response.checkout_request_id,
                merchant_request_id=response.merchant_request_id,
                amount=amount,
                phone_number=phone_number,
                is_success=False 
            )
            
            return JsonResponse({"status": "success", "response": str(response)})
        
        except Order.DoesNotExist:
            return JsonResponse({"status": "error", "message": "No orders found in database"}, status=404)
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)
    
    return JsonResponse({"status": "error", "message": "Invalid request"}, status=400)


@csrf_exempt
def mpesa_callback(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            stk_callback = data['Body']['stkCallback']
            
            checkout_id = stk_callback['CheckoutRequestID']
            result_code = stk_callback['ResultCode']
            result_desc = stk_callback['ResultDesc']
            
            # Fetch the record initiated earlier
            transaction = MpesaTransaction.objects.get(checkout_request_id=checkout_id)
            transaction.response_description = result_desc
            
            if result_code == 0:
                # Success! Extract metadata
                metadata = stk_callback['CallbackMetadata']['Item']
                
                for item in metadata:
                    name = item.get('Name')
                    value = item.get('Value')
                    
                    if name == 'MpesaReceiptNumber':
                        transaction.receipt_number = value
                    elif name == 'TransactionDate':
                        # Format: 20260415093015
                        transaction.transaction_date = datetime.strptime(str(value), '%Y%m%d%H%M%S')
                
                transaction.is_success = True
                
                # Update Order Status automatically
                order = transaction.order
                order.status = 'Completed' # Or whatever choice matches your Order model
                order.save()

            else:
                transaction.is_success = False
            
            transaction.save()
            return JsonResponse({"ResultCode": 0, "ResultDesc": "Success"})

        except MpesaTransaction.DoesNotExist:
            return JsonResponse({"ResultCode": 1, "ResultDesc": "Transaction not found"}, status=404)
        except Exception as e:
            return JsonResponse({"ResultCode": 1, "ResultDesc": str(e)}, status=500)

    return JsonResponse({"status": "error"}, status=400)