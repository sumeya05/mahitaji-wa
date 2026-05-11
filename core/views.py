from urllib import request

from django.shortcuts import render, redirect, get_object_or_404
from rest_framework import viewsets, permissions
from django.contrib.auth import logout, login, authenticate
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django_daraja.mpesa.core import MpesaClient
import json
from datetime import datetime
from django.urls import reverse
from django.db.models import F, Count


from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes

import google.generativeai as genai
from django.conf import settings


# --- Protected Views ---
from django.contrib.auth.decorators import login_required

from django.contrib.auth import update_session_auth_hash

# Import models, serializers, and the RegisterForm we'll create
from .models import (
    Product, Category, Order, CustomerProfile, 
    MpesaTransaction, Address
)
from .serializers import (
    ProductSerializer, CategorySerializer, OrderSerializer
)
from .forms import RegisterForm  # Make sure to create this in core/forms.py


# 1. Template & Auth Views

def home(request):
    # 1. New Products: Ordered by newest first
    new_products = Product.objects.filter(is_active=True).order_by('-created_at')[:8]
    
    # 2. Top Offers: Products where old_price is greater than retail_price
    top_offers = Product.objects.filter(
        is_active=True, 
        old_price__gt=F('retail_price')
    ).order_by('-id')[:8]
    
    # 3. Trending Section (Dynamic Categories)
    # We find the top 2 categories that have the most active products
    top_categories = Category.objects.annotate(
        product_count=Count('products')
    ).filter(product_count__gt=0).order_by('-product_count')[:2]

    # We build a list containing the category and its products for the tabs
    trending_data = []
    for cat in top_categories:
        trending_data.append({
            'category': cat,
            'products': Product.objects.filter(category=cat, is_active=True)[:8]
        })
    
    # 4. Bestsellers: Products specifically marked as best sellers
    # (Ensure you have 'is_best_seller' field in your Product model)
    bestsellers = Product.objects.filter(is_active=True, is_best_seller=True)[:8]

    context = {
        'new_products': new_products,
        'top_offers': top_offers,
        'trending_data': trending_data, # Use this for your dynamic tabs
        'bestsellers': bestsellers,
    }
    
    return render(request, 'core/home.html', context)



def retailers(request):
    # Fetch active products and optimize for brand and UOM lookup
    all_products = Product.objects.filter(is_active=True).select_related('brand', 'unit_of_measure')
    context = {
        'products': all_products
    }
    return render(request, 'core/retailers.html', context)


def wholesalers(request):
    # Fetch active products for wholesalers
    products = Product.objects.filter(is_active=True).select_related('brand')
    return render(request, 'core/wholesalers.html', {'products': products})

def products(request):
    # Fetch all active products for the general catalog
    products = Product.objects.filter(is_active=True).select_related('brand')
    return render(request, 'core/products.html', {'products': products})

def product_detail(request, pk):
    product = get_object_or_404(Product, pk=pk)
    # Fetch related products from the same category, excluding the current one
    related_products = Product.objects.filter(
        category=product.category, 
        is_active=True
    ).exclude(pk=pk)[:10]
    
    return render(request, 'core/product-detail.html', {
        'product': product,
        'related_products': related_products
    })







def search(request):
    return render(request, 'core/search.html')

def shopping_cart(request):
    return render(request, 'core/shopping-cart.html')

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
                # reverse('dashboard') looks up the actual URL path automatically
                return JsonResponse({
                    "success": True, 
                    "redirect_url": reverse('dashboard') 
                })
        
        # 3. Handle Invalid Credentials
        error_msg = "Invalid username/email or password."
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": error_msg}, status=400)
        
        messages.error(request, error_msg)
    
    return render(request, 'core/login.html', {'form': AuthenticationForm()})

def register_view(request):
    """Hybrid Register: Creates User + CustomerProfile + Initial Address"""
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            # 1. Save the User
            user = form.save()
            
            # 2. Get extra fields from POST
            tax_id = request.POST.get('tax_id', '').strip()
            billing_addr_text = request.POST.get('billing_address', '').strip()
            phone = request.POST.get('phone_number', '') # Assuming you have a phone field

            # 3. Update the Profile (In case a signal already created it)
            profile, created = CustomerProfile.objects.update_or_create(
                user=user,
                defaults={
                    'tax_id': tax_id,
                    'phone_number': phone,
                }
            )

            # 4. Save Billing Address if provided
            if billing_addr_text:
                Address.objects.create(
                    customer=profile,
                    label="Billing Address",
                    physical_address=billing_addr_text,
                    is_primary=True
                )

            # 5. Log the user in
            login(request, user)
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    "success": True, 
                    "redirect_url": "/dashboard/"
                })
            return redirect('dashboard')
        
        # AJAX Validation Errors
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                "success": False, 
                "errors": form.errors.get_json_data()
            }, status=400)
    
    else:
        form = RegisterForm()
    
    return render(request, 'core/register.html', {'form': form})

def logout_view(request):
    logout(request)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({"success": True, "redirect_url": "/"})
    return redirect('home')

# User views
def wishlist(request):
    return render(request, 'core/wishlist.html')

@login_required
def dashboard(request):
    user = request.user
    profile = user.customerprofile
    
    # Fetch real orders for this customer
    user_orders = profile.orders.all().order_by('-created_at')
    
    # Optional: Get the 5 most recent for a "Recent Orders" summary
    recent_orders = user_orders[:5]
    
    # Get primary address for the Address tab
    primary_address = profile.addresses.filter(is_primary=True).first()
    
    context = {
        'user': user,
        'profile': profile,
        'user_orders': user_orders,
        'recent_orders': recent_orders,
        'primary_address': primary_address,
    }
    return render(request, 'core/dashboard.html', context)

@login_required
def transactions(request):
    return render(request, 'core/transactions.html')

@login_required
def addresses(request):
    return render(request, 'core/addresses.html')

@login_required
def payment_methods(request):
    return render(request, 'core/payment-methods.html')


# Helpdesk & Informational Views
def pickups(request):
    return render(request, 'core/pickups-deliveries.html')

def payment_info(request):
    return render(request, 'core/payment-info.html')

def returns(request):
    return render(request, 'core/return-policy.html')

def faqs(request):
    return render(request, 'core/faqs.html')

def terms(request):
    return render(request, 'core/terms.html')   

def contact(request):
    return render(request, 'core/contact-us.html') 

def about(request):
    return render(request, 'core/about-us.html')

def statement(request):
    return render(request, 'core/our-statement.html')

def location(request):
    return render(request, 'core/our-location.html')


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
                # In views.py Step 3
                order_instance = Order.objects.filter(customer__user=request.user).latest('id')
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




# Setup your API Key (Get one from Google AI Studio)
# genai.configure(api_key="AIzaSyDb8cKq0rjT8FQLWeSthBIj7pqevFIvaW8")
# genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
genai.configure(api_key=settings.GEMINI_API_KEY)

# In views.py
def ai_assistant_chat(request):
    if request.method == "POST":
        user_message = request.POST.get('message')
        
        # Change from 'gemini-1.5-flash' to:
        # In views.py, update this line:
        #model = genai.GenerativeModel('models/gemini-1.5-flash')

        # Safe way to get business name even if customerprofile is missing
        # Change this line:
        business = request.user.customerprofile.business_name

        # To this (Safer):
        business = getattr(request.user, 'customerprofile', None)
        business_name = business.business_name if business else "their business"
        
        context = (
            f"You are the Mahitaji Wholesale Assistant. "
            f"The user is {request.user.first_name} {request.user.last_name} "
            f"representing {business_name}."
        )
        # Wrap in a try-except to catch API errors (like quota or invalid key)
        try:
            # Use the EXACT name from your terminal output
            model = genai.GenerativeModel('models/gemini-2.0-flash')
            
            context = "You are the Mahitaji Wholesale Assistant."
            response = model.generate_content(f"{context}\n\nUser: {user_message}")
            
            return JsonResponse({'reply': response.text})
            
        except Exception as e:
            if "429" in str(e):
                return JsonResponse({'reply': "I'm a bit busy helping other retailers. Please wait 30 seconds and try again!"})
            return JsonResponse({'reply': f"Error: {str(e)}"})
        

from django.contrib.auth import update_session_auth_hash


@login_required
def update_account(request):
    if request.method == 'POST':
        user = request.user
        profile, created = CustomerProfile.objects.get_or_create(user=user)

        # 1. Update Basic User Info
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.email = request.POST.get('email', user.email)

        # 2. Profile Specific Info
        profile.business_name = request.POST.get('billing_full_name', profile.business_name)
        profile.tax_id = request.POST.get('tax_id', profile.tax_id)
        
        # M-Pesa / Phone Update
        if 'mpesa_number' in request.POST:
            profile.phone_number = request.POST.get('mpesa_number')
        elif 'delivery_phone' in request.POST:
            profile.phone_number = request.POST.get('delivery_phone')

        # 3. Address Logic (Fixing the AttributeError)
        new_address_text = request.POST.get('address')
        new_city = request.POST.get('city')
        
        if new_address_text:
            # Get existing primary address or create a new one for this customer
            address_obj, addr_created = Address.objects.get_or_create(
                customer=profile,
                is_primary=True,
                defaults={'label': 'Billing Address', 'physical_address': new_address_text, 'city': new_city or 'Nairobi'}
            )
            
            if not addr_created:
                # If it already existed, update the fields
                address_obj.physical_address = new_address_text
                if new_city:
                    address_obj.city = new_city
                address_obj.save()

        # 4. Password Logic (Remains the same)
        new_pass = request.POST.get('new_password')
        if new_pass:
            current_pass = request.POST.get('current_password')
            confirm_pass = request.POST.get('confirm_password')
            if not user.check_password(current_pass):
                return JsonResponse({'error': 'Current password incorrect'}, status=400)
            if new_pass != confirm_pass:
                return JsonResponse({'error': 'Passwords do not match'}, status=400)
            user.set_password(new_pass)
            user.save()
            update_session_auth_hash(request, user)

        user.save()
        profile.save()

        return JsonResponse({'message': 'Profile updated successfully!'})

    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
def get_order_details(request, order_id):
    order = get_object_or_404(Order, id=order_id, customer=request.user.customerprofile)
    # This should return a small HTML snippet of a table with the items
    return render(request, 'core/order_item.html', {'order': order})