from django import forms
from django.contrib.auth.models import User
from django.utils.text import slugify
from .models import CustomerProfile

class RegisterForm(forms.ModelForm):
    # Individual name fields to match the new front-end
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    
    business_name = forms.CharField(max_length=255, required=False)
    phone_number = forms.CharField(max_length=15, required=True)
    tax_id = forms.CharField(max_length=15, required=False, label="KRA PIN") 
    
    password = forms.CharField(widget=forms.PasswordInput())
    confirm_password = forms.CharField(widget=forms.PasswordInput())

    class Meta:
        model = User
        fields = ['email', 'password']

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password != confirm_password:
            raise forms.ValidationError("Passwords do not match")
        return cleaned_data    
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        
        # Use business_name if it exists
        # Otherwise, combine first and last name for the slug
        business_name = self.cleaned_data.get('business_name')
        if business_name:
            name_for_slug = business_name
        else:
            name_for_slug = f"{user.first_name} {user.last_name}"
        
        base_username = slugify(name_for_slug)
        
        # Handle potential duplicates
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}-{counter}"
            counter += 1
            
        user.username = username
        user.set_password(self.cleaned_data["password"])
        
        if commit:
            user.save()
            CustomerProfile.objects.create(
                user=user,
                business_name=business_name,
                contact_person=f"{user.first_name} {user.last_name}",
                phone_number=self.cleaned_data['phone_number'],
                tax_id=self.cleaned_data.get('tax_id')
            )
        return user