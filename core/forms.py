from django import forms
from django.contrib.auth.models import User
from .models import CustomerProfile

class RegisterForm(forms.ModelForm):
    # We add these extra fields to the standard User form
    email = forms.EmailField(required=True)
    phone_number = forms.CharField(max_length=15, required=True, help_text="Format: 2547XXXXXXXX")
    password = forms.CharField(widget=forms.PasswordInput, min_length=8)
    confirm_password = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ['username', 'email', 'password']

    def clean_username(self):
        username = self.cleaned_data.get('username').lower()
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password != confirm_password:
            raise forms.ValidationError("Passwords do not match.")
        return cleaned_data

    def save(self, commit=True):
        # 1. Save the User object
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
            
            # 2. Automatically create the CustomerProfile
            # We default 'is_wholesaler' to False; you can change this 
            # based on your specific business onboarding flow.
            CustomerProfile.objects.create(
                user=user,
                phone_number=self.cleaned_data['phone_number'],
                is_wholesaler=False 
            )
        return user