from django import forms
from django.contrib.auth.models import User
from django.utils.text import slugify
from .models import CustomerProfile

class RegisterForm(forms.ModelForm):
    business_name = forms.CharField(max_length=255, required=True)
    contact_person = forms.CharField(max_length=255, required=True)
    phone_number = forms.CharField(max_length=15, required=True)
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
        # Convert "Trial Shop" to "trial-shop" for the User model
        base_username = slugify(self.cleaned_data['business_name'])
        
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}-{counter}"
            counter += 1
            
        user.username = username
        user.set_password(self.cleaned_data["password"])
        
        if commit:
            user.save()
            # Successfully create profile with the now-existing fields
            CustomerProfile.objects.create(
                user=user,
                business_name=self.cleaned_data['business_name'],
                contact_person=self.cleaned_data['contact_person'],
                phone_number=self.cleaned_data['phone_number']
            )
        return user