from django.shortcuts import render, redirect
from rest_framework import viewsets, permissions
from django.contrib.auth import logout, login, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django_daraja.mpesa.core import MpesaClient
import json
from datetime import datetime



from django.contrib.auth.models import User
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes


# --- Protected Views ---
from django.contrib.auth.decorators import login_required

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
    """Hybrid Login: Handles both AJAX and standard POST for Username/Email"""
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == "POST":
        login_input = request.POST.get('username')
        password = request.POST.get('password')
        
        # 1. Try to find the user by email first
        if '@' in login_input:
            try:
                user_obj = User.objects.get(email=login_input)
                username = user_obj.username
            except User.DoesNotExist:
                username = login_input  # Fallback to the input string
        else:
            username = login_input

        # 2. Use the resolved username to authenticate
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"success": True, "redirect_url": "/dashboard/"})
            return redirect('dashboard')
        
        # 3. Handle Invalid Credentials
        error_msg = "Invalid username/email or password."
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": error_msg}, status=400)
        
        messages.error(request, error_msg)
    
    return render(request, 'core/login.html', {'form': AuthenticationForm()})

def signup(request):
    """Hybrid Signup: Creates User + CustomerProfile with AJAX support"""
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    "success": True, 
                    "redirect_url": "/dashboard/"
                })
            return redirect('dashboard')
        
        # If form is invalid and it's an AJAX request
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            # .get_json_data() provides a clean dictionary of error messages
            return JsonResponse({
                "success": False, 
                "errors": form.errors.get_json_data()
            }, status=400)
    
    else:
        form = RegisterForm()
    
    return render(request, 'core/signup.html', {'form': form})

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
import json
from django.http import JsonResponse
from django.urls import reverse
from django_daraja.mpesa.core import MpesaClient

def initiate_stk_push(request):
    if request.method == "POST":
        try:
            # 1. Parse data from frontend
            data = json.loads(request.body)
            raw_phone = data.get('phone')
            # Ensure amount is an integer for Safaricom's API
            amount = int(data.get('amount', 1))

            # 2. Format phone (ensures 254... format)
            if raw_phone.startswith('0'):
                phone_number = '254' + raw_phone[1:]
            elif raw_phone.startswith('7'):
                phone_number = '254' + raw_phone
            else:
                phone_number = raw_phone

            # 3. Handle the Order
            try:
                order_instance = Order.objects.latest('id')
            except Order.DoesNotExist:
                order_instance = None 

            # 4. M-Pesa Configuration
            cl = MpesaClient()
            account_reference = 'Mahitaji_Order'
            transaction_desc = 'Wholesale Payment'
            # Use ngrok URL for local testing or request.build_absolute_uri(reverse('callback'))
            callback_url = 'https://abc6-185-177-124-199.ngrok-free.app/mpesa/callback/'
            
            # Trigger the STK Push
            response = cl.stk_push(phone_number, amount, account_reference, transaction_desc, callback_url)

            # 5. Prevent Duplicate Entry error
            # If a transaction for this order exists, update it; otherwise, create it.
            if order_instance:
                MpesaTransaction.objects.update_or_create(
                    order=order_instance,
                    defaults={
                        'checkout_request_id': response.checkout_request_id,
                        'merchant_request_id': response.merchant_request_id,
                        'amount': amount,
                        'phone_number': phone_number,
                        'is_success': False 
                    }
                )
            
            return JsonResponse({"status": "success", "response": str(response)})
        
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






def custom_password_reset(request):
    if request.method == "POST":
        form = PasswordResetForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            users = User.objects.filter(email=email)
            if users.exists():
                form.save(
                    request=request,
                    use_https=request.is_secure(),
                    email_template_name='core/password_reset_email.html',
                    subject_template_name='core/password_reset_subject.txt',
                )
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({"success": True, "redirect_url": "/password-reset/done/"})
                return redirect('password_reset_done')
            else:
                error_msg = "No account found with that email."
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({"success": False, "error": error_msg}, status=400)
                messages.error(request, error_msg)
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"success": False, "errors": form.errors}, status=400)
    
    return render(request, 'core/password_reset.html', {'form': PasswordResetForm()})

def custom_password_reset_confirm(request, uidb64, token):
    user = None  # Initialize user here
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist, UnicodeDecodeError):
        user = None

    # Now 'user' is guaranteed to be defined (either as a User object or None)
    if user is not None and default_token_generator.check_token(user, token):
        if request.method == 'POST':
            form = SetPasswordForm(user, request.POST)
            if form.is_valid():
                form.save()
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({"success": True, "redirect_url": "/reset/done/"})
                return redirect('password_reset_complete')
            else:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({"success": False, "errors": form.errors}, status=400)
        else:
            form = SetPasswordForm(user)
        return render(request, 'core/password_reset_confirm.html', {'form': form})
    else:
        # Link is invalid or expired
        return render(request, 'core/password_reset_invalid.html')




# Simple Template Views
def password_reset_done(request):
    return render(request, 'core/password_reset_done.html')

def password_reset_complete(request):
    return render(request, 'core/password_reset_complete.html')