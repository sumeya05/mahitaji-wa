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
from django.db.models import F, Q, Count

from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes

import google.generativeai as genai
from django.conf import settings
from django_daraja.mpesa.core import MpesaClient

from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from .models import (
    Product, Category, Brand, Order, CustomerProfile, 
    MpesaTransaction, Address, OrderItem
)
from .serializers import (
    ProductSerializer, CategorySerializer, OrderSerializer
)
from .forms import RegisterForm  
from .cart import Cart



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
    # 1. Start with all active products
    all_products = Product.objects.filter(is_active=True).select_related('brand', 'unit_of_measure')

    # 2. Grab filter data from the GET request
    selected_brands = request.GET.getlist('brand')
    selected_cats = request.GET.getlist('category_filter')

    # 3. Apply Brand Filter if any are checked
    if selected_brands:
        all_products = all_products.filter(brand_id__in=selected_brands)

    # 4. Apply Category Filter if any are checked
    if selected_cats:
        all_products = all_products.filter(category_id__in=selected_cats)

    context = {
        'products': all_products.distinct(), # Use your variable name 'products'
        'selected_brands': selected_brands,
        'selected_cats': selected_cats,
    }
    return render(request, 'core/retailers.html', context)


def wholesalers(request):
    # Get initial queryset (Following your existing logic)
    all_products = Product.objects.filter(is_active=True).select_related('brand', 'unit_of_measure')

    # Grab filter data from the GET request
    selected_brands = request.GET.getlist('brand')
    selected_cats = request.GET.getlist('category_filter')

    # Apply Filters
    if selected_brands:
        all_products = all_products.filter(brand_id__in=selected_brands)
    if selected_cats:
        all_products = all_products.filter(category_id__in=selected_cats)

    context = {
        'products': all_products.distinct(), # Variable name used in your template
        'selected_brands': selected_brands,
        'selected_cats': selected_cats,
    }
    return render(request, 'core/wholesalers.html', context)

def products(request):
    # This usually shows the full catalog
    all_products = Product.objects.filter(is_active=True).select_related('brand', 'unit_of_measure')

    selected_brands = request.GET.getlist('brand')
    selected_cats = request.GET.getlist('category_filter')

    if selected_brands:
        all_products = all_products.filter(brand_id__in=selected_brands)
    if selected_cats:
        all_products = all_products.filter(category_id__in=selected_cats)

    context = {
        'products': all_products.distinct(),
        'selected_brands': selected_brands,
        'selected_cats': selected_cats,
    }
    return render(request, 'core/products.html', context)

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
    query = request.GET.get('q')
    
    # Get lists of selected IDs from the checkboxes
    selected_brands = request.GET.getlist('brand')
    selected_cats = request.GET.getlist('category_filter')
    
    products = Product.objects.filter(is_active=True)
    
    # 1. Text Search
    if query:
        products = products.filter(
            Q(name__icontains=query) | 
            Q(description__icontains=query) |
            Q(brand__name__icontains=query)
        )

    # 2. Filter by Brand (Multiple)
    if selected_brands:
        products = products.filter(brand_id__in=selected_brands)

    # 3. Filter by Category (Multiple)
    if selected_cats:
        products = products.filter(category_id__in=selected_cats)

    return render(request, 'core/search.html', {
        'products': products.distinct(),
        'query': query,
        'selected_brands': selected_brands,
        'selected_cats': selected_cats,
        'brands': Brand.objects.annotate(p_count=Count('products')).filter(p_count__gt=0),
    })

def shopping_cart(request):
    """Renders the main cart page"""
    cart = Cart(request)
    return render(request, 'core/shopping-cart.html', {'cart': cart})

def cart_add(request):
    """Handles adding products to the cart via AJAX"""
    cart = Cart(request)
    if request.POST.get('action') == 'post':
        product_id = int(request.POST.get('product_id'))
        product_qty = int(request.POST.get('product_qty'))
        product = get_object_or_404(Product, id=product_id)
        
        cart.add(product=product, quantity=product_qty)
        
        cart_quantity = cart.__len__()
        response = JsonResponse({'qty': cart_quantity})
        return response

def cart_delete(request):
    """Removes an item from the cart via AJAX"""
    cart = Cart(request)
    if request.POST.get('action') == 'post':
        product_id = int(request.POST.get('product_id'))
        cart.delete(product_id=product_id)
        
        cart_quantity = cart.__len__()
        cart_total = cart.get_total_price()
        response = JsonResponse({'qty': cart_quantity, 'total': cart_total})
        return response

def cart_update(request):
    """Updates the quantity of an item already in the cart"""
    cart = Cart(request)
    if request.POST.get('action') == 'post':
        product_id = int(request.POST.get('product_id'))
        product_qty = int(request.POST.get('product_qty'))
        
        cart.update(product_id=product_id, qty=product_qty)
        
        cart_quantity = cart.__len__()
        cart_total = cart.get_total_price()
        response = JsonResponse({'qty': cart_quantity, 'total': cart_total})
        return response




@login_required
def checkout(request):
    cart = Cart(request)
    # Get the user's profile
    profile = get_object_or_404(CustomerProfile, user=request.user)
    
    # Fetch the billing address specifically
    primary_address = Address.objects.filter(customer=profile, label='Billing Address').first()

    context = {
        'cart': cart,
        'profile': profile,
        'primary_address': primary_address, # This matches your dashboard logic
    }
    return render(request, 'core/checkout.html', context)

import uuid
@login_required
def place_order(request):
    if request.method == 'POST':
        try:
            cart = Cart(request)
            data = json.loads(request.body)
            order_number = str(uuid.uuid4()).split('-')[0].upper() 
            # 1. Create the Order (The Anchor)s
            order = Order.objects.create(
                order_number=f"MAH-{order_number}", # Generates a short unique ID
                customer=request.user.customerprofile,
                full_name=f"{data.get('first_name')} {data.get('last_name')}",
                email=data.get('email'),
                phone=data.get('phone'),
                address=data.get('address'),
                city=data.get('city', 'Nairobi'),
                total_amount=cart.get_total_price(), # Corrected field name
                status='PENDING' # Consistent with STATUS_CHOICES
            )
    

            # 2. Save Order Items
            for item in cart:
                OrderItem.objects.create(
                    order=order,
                    product=item['product'],
                    price_at_purchase=item['price'], # Corrected field name
                    quantity=item['qty']
                )

            payment_method = data.get('payment_method')
            
            # 3. Return response for Step 2
            return JsonResponse({
                'status': 'success',
                'order_id': order.id,
                'payment_method': payment_method,
                'order_number': order.order_number
            })

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)



@login_required
def order_success(request, order_number):
    order = get_object_or_404(Order, order_number=order_number)
    
    # Initialize and clear the cart
    cart = Cart(request)
    cart.clear()
    
    # EXTRA SAFETY: Manually pop the key using the string 'cart' 
    # and 'session_cart' just in case there's a naming mismatch
    request.session.pop('cart', None)
    request.session.pop('session_cart', None)
    
    # Mark as modified to ensure the deletions above are committed
    request.session.modified = True
    
    return render(request, 'core/order-success.html', {'order': order})




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


@login_required
def initiate_stk_push(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            order_id = data.get('order_id')
            order = get_object_or_404(Order, id=order_id)
            
            # Safeguard: Normalizing phone number
            raw_phone = data.get('phone')
            if raw_phone.startswith('0'):
                phone_number = '254' + raw_phone[1:]
            elif raw_phone.startswith('7') or raw_phone.startswith('1'): # Supports newer 01... prefixes
                phone_number = '254' + raw_phone
            else:
                phone_number = raw_phone

            # M-Pesa Configuration
            cl = MpesaClient()
            amount = int(order.total_amount)
            account_ref = f"Order_{order.id}"
            callback_url = 'https://your-ngrok-url.ngrok-free.app/mpesa/callback/'
            
            response = cl.stk_push(phone_number, amount, account_ref, 'Mahitaji Payment', callback_url)

            # Log Transaction with Order link
            MpesaTransaction.objects.update_or_create(
                order=order,
                defaults={
                    'checkout_request_id': response.checkout_request_id,
                    'merchant_request_id': response.merchant_request_id,
                    'amount': amount,
                    'phone_number': phone_number,
                    'is_success': False
                }
            )
            
            return JsonResponse({"status": "success", "checkout_id": response.checkout_request_id})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)
        
@login_required
def check_payment_status(request, order_number):
    order = get_object_or_404(Order, order_number=order_number)
    # Check if a successful transaction exists for this order
    transaction = MpesaTransaction.objects.filter(order=order, is_success=True).exists()
    
    if transaction:
        return JsonResponse({'status': 'paid'})
    return JsonResponse({'status': 'pending'})


@csrf_exempt
def mpesa_callback(request):
    try:
        data = json.loads(request.body)
        stk_callback = data['Body']['stkCallback']
        result_code = stk_callback['ResultCode']
        checkout_request_id = stk_callback['CheckoutRequestID']

        # Find the specific transaction
        transaction = MpesaTransaction.objects.get(checkout_request_id=checkout_request_id)

        if result_code == 0:
            # Successful Payment - Parse Metadata items
            metadata = stk_callback['CallbackMetadata']['Item']
            receipt_no = ""
            for item in metadata:
                if item['Name'] == 'MpesaReceiptNumber':
                    receipt_no = item['Value']
            
            # Update Transaction
            transaction.is_success = True
            transaction.mpesa_receipt_number = receipt_no # Ensure this field exists in your model
            transaction.save()

            # Update Order
            order = transaction.order
            order.payment_status = 'Paid'
            order.save()
            
            return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})
        else:
            # Failed Payment
            transaction.is_success = False
            transaction.save()
            return JsonResponse({"ResultCode": result_code, "ResultDesc": "Payment Failed"})
            
    except Exception as e:
        return JsonResponse({"ResultCode": 1, "ResultDesc": f"Internal Error: {str(e)}"})




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