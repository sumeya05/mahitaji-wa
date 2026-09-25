import re

from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.utils.text import slugify

from .models import Address, ContactMessage, CustomerProfile

PHONE_RE = re.compile(r'^(?:\+?254|0)?(7\d{8}|1\d{8})$')


def normalize_phone(value):
    """Return a Kenyan MSISDN in 2547XXXXXXXX / 2541XXXXXXXX form, or None if invalid."""
    digits = re.sub(r'\D', '', value or '')
    match = PHONE_RE.match(digits) or PHONE_RE.match((value or '').strip())
    if not match:
        return None
    return '254' + match.group(1)


class RegisterForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    business_name = forms.CharField(max_length=255, required=False)
    phone_number = forms.CharField(max_length=15, required=True)
    tax_id = forms.CharField(max_length=15, required=False, label="KRA PIN")
    billing_address = forms.CharField(max_length=500, required=False)
    city = forms.CharField(max_length=100, required=False)
    password = forms.CharField(widget=forms.PasswordInput())
    confirm_password = forms.CharField(widget=forms.PasswordInput())

    class Meta:
        model = User
        fields = ['email', 'password']

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if not email:
            raise forms.ValidationError("An email address is required.")
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists. Try logging in instead.")
        return email

    def clean_phone_number(self):
        phone = normalize_phone(self.cleaned_data.get('phone_number'))
        if not phone:
            raise forms.ValidationError("Enter a valid Kenyan mobile number, e.g. 0712 345 678.")
        return phone

    def clean_tax_id(self):
        tax_id = (self.cleaned_data.get('tax_id') or '').strip().upper()
        if tax_id and not re.match(r'^[AP]\d{9}[A-Z]$', tax_id):
            raise forms.ValidationError("KRA PIN should look like A012345678Z.")
        return tax_id or None

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password')
        confirm = cleaned.get('confirm_password')
        if password and confirm and password != confirm:
            self.add_error('confirm_password', "Passwords do not match.")
        if password:
            try:
                validate_password(password)
            except forms.ValidationError as exc:
                self.add_error('password', exc)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data['first_name'].strip()
        user.last_name = self.cleaned_data['last_name'].strip()
        business_name = (self.cleaned_data.get('business_name') or '').strip()
        base_username = slugify(business_name or f"{user.first_name} {user.last_name}") or 'customer'
        username, counter = base_username, 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}-{counter}"
            counter += 1
        user.username = username
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            profile = CustomerProfile.objects.create(
                user=user,
                business_name=business_name or None,
                contact_person=f"{user.first_name} {user.last_name}",
                phone_number=self.cleaned_data['phone_number'],
                tax_id=self.cleaned_data.get('tax_id'),
            )
            billing = (self.cleaned_data.get('billing_address') or '').strip()
            if billing:
                Address.objects.create(
                    customer=profile,
                    label="Delivery Address",
                    physical_address=billing,
                    city=(self.cleaned_data.get('city') or '').strip() or 'Nairobi',
                    is_primary=True,
                )
        return user


class AccountForm(forms.Form):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    business_name = forms.CharField(max_length=255, required=False)
    phone_number = forms.CharField(max_length=20, required=True)
    tax_id = forms.CharField(max_length=15, required=False)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("That email is already used by another account.")
        return email

    def clean_phone_number(self):
        phone = normalize_phone(self.cleaned_data.get('phone_number'))
        if not phone:
            raise forms.ValidationError("Enter a valid Kenyan mobile number.")
        return phone

    def clean_tax_id(self):
        tax_id = (self.cleaned_data.get('tax_id') or '').strip().upper()
        if tax_id and not re.match(r'^[AP]\d{9}[A-Z]$', tax_id):
            raise forms.ValidationError("KRA PIN should look like A012345678Z.")
        return tax_id or None


class PasswordChangeForm(forms.Form):
    current_password = forms.CharField(widget=forms.PasswordInput())
    new_password = forms.CharField(widget=forms.PasswordInput())
    confirm_password = forms.CharField(widget=forms.PasswordInput())

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        value = self.cleaned_data['current_password']
        if not self.user.check_password(value):
            raise forms.ValidationError("Your current password is incorrect.")
        return value

    def clean(self):
        cleaned = super().clean()
        new, confirm = cleaned.get('new_password'), cleaned.get('confirm_password')
        if new and confirm and new != confirm:
            self.add_error('confirm_password', "New passwords do not match.")
        if new:
            try:
                validate_password(new, self.user)
            except forms.ValidationError as exc:
                self.add_error('new_password', exc)
        return cleaned


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ['label', 'physical_address', 'city', 'is_primary']

    def clean_label(self):
        return (self.cleaned_data.get('label') or '').strip() or 'Delivery Address'

    def clean_city(self):
        return (self.cleaned_data.get('city') or '').strip() or 'Nairobi'


class CheckoutForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField()
    phone = forms.CharField(max_length=20)
    address = forms.CharField(max_length=500)
    city = forms.CharField(max_length=100, required=False)
    notes = forms.CharField(max_length=1000, required=False)
    payment_method = forms.ChoiceField(choices=(('cod', 'Cash on Delivery'), ('mpesa', 'M-Pesa')))
    mpesa_phone = forms.CharField(max_length=20, required=False)
    save_address = forms.BooleanField(required=False)

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data.get('phone'))
        if not phone:
            raise forms.ValidationError("Enter a valid Kenyan mobile number.")
        return phone

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('payment_method') == 'mpesa':
            mpesa_phone = normalize_phone(cleaned.get('mpesa_phone') or cleaned.get('phone'))
            if not mpesa_phone:
                self.add_error('mpesa_phone', "Enter the M-Pesa number that should receive the payment prompt.")
            cleaned['mpesa_phone'] = mpesa_phone
        cleaned['city'] = (cleaned.get('city') or '').strip() or 'Nairobi'
        return cleaned


class ContactForm(forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ['full_name', 'business_name', 'email', 'phone', 'inquiry_type', 'message']

    def clean_message(self):
        message = (self.cleaned_data.get('message') or '').strip()
        if len(message) < 10:
            raise forms.ValidationError("Tell us a little more so we can help (at least 10 characters).")
        return message


class NewsletterForm(forms.Form):
    # Not a ModelForm: an existing subscriber must be able to submit again without
    # tripping the unique-email validation (the view uses get_or_create).
    email = forms.EmailField(max_length=254)

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()
