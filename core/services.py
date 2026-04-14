import requests
import base64
from datetime import datetime
from django.conf import settings # Accesses your settings.py variables

class MpesaService:
    def __init__(self):
        # Pulling from settings.py (which pulls from .env)
        self.consumer_key = settings.MPESA_CONSUMER_KEY
        self.consumer_secret = settings.MPESA_CONSUMER_SECRET
        self.shortcode = settings.MPESA_SHORTCODE
        self.passkey = settings.MPESA_PASSKEY
        
        # URLs (Safaricom Sandbox)
        self.auth_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
        self.stk_push_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"

    def get_token(self):
        """Generates the OAuth Access Token"""
        try:
            res = requests.get(self.auth_url, auth=(self.consumer_key, self.consumer_secret))
            res.raise_for_status()
            return res.json().get('access_token')
        except Exception as e:
            print(f"Error generating M-Pesa token: {e}")
            return None

    def initiate_stk_push(self, phone_number, amount, order_number):
        """Sends the STK Push request to the phone"""
        token = self.get_token()
        if not token:
            return {"Error": "Failed to get access token"}

        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        
        # Password generation: base64(shortcode + passkey + timestamp)
        password_str = self.shortcode + self.passkey + timestamp
        password = base64.b64encode(password_str.encode()).decode('utf-8')
        
        headers = {"Authorization": f"Bearer {token}"}
        
        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": int(amount),
            "PartyA": phone_number, # Format: 2547XXXXXXXX
            "PartyB": self.shortcode,
            "PhoneNumber": phone_number,
            "CallBackURL": settings.MPESA_CALLBACK_URL,
            "AccountReference": order_number,
            "TransactionDesc": f"Payment for Order {order_number}"
        }

        try:
            response = requests.post(self.stk_push_url, json=payload, headers=headers)
            return response.json()
        except Exception as e:
            return {"Error": str(e)}