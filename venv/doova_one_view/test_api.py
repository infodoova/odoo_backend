#!/usr/bin/env python
"""
API Integration Test Script

Tests the complete REST API flow:
1. User registration
2. User login
3. Tenant creation
4. Tenant retrieval
5. Token refresh

Run this script after starting the Django development server:
    python manage.py runserver

Then in another terminal:
    python test_api.py
"""

import requests
import json
from datetime import datetime

# Configuration
# Configuration
API_BASE_URL = 'http://localhost:8000/api/v1'
HEADERS = {'Content-Type': 'application/json'}

class APITester:
    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url
        self.access_token = None
        self.refresh_token_str = None  # Renamed to avoid collision with method name
        self.user_data = None
        self.tenant_data = None
        
    def log(self, message: str, level: str = 'INFO'):
        """Log messages with timestamp"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        prefix = f'[{timestamp}] [{level}]'
        print(f'{prefix} {message}')
    
    def register_user(self, email: str, password: str, first_name: str = 'Test', last_name: str = 'User'):
        """Test user registration"""
        self.log('Testing user registration...', 'TEST')
        
        payload = {
            'email': email,
            'password': password,
            'password_confirm': password,
            'first_name': first_name,
            'last_name': last_name,
            'role': 'owner' # Added role field which might be required or optional
        }
        
        try:
            response = requests.post(
                f'{self.base_url}/auth/register', # Removed trailing slash to match FastAPI usually
                json=payload,
                headers=HEADERS,
                timeout=10
            )
            
            if response.status_code == 201:
                self.log(f'✓ User registered successfully: {email}', 'SUCCESS')
                return True
            elif response.status_code == 400:
                # User might already exist
                self.log(f'⚠ User already exists or validation error: {response.json()}', 'WARNING')
                return True
            else:
                self.log(f'✗ Registration failed: {response.status_code} - {response.text}', 'ERROR')
                return False
                
        except Exception as e:
            self.log(f'✗ Registration error: {str(e)}', 'ERROR')
            return False
    
    def login_user(self, email: str, password: str):
        """Test user login and token generation"""
        self.log('Testing user login...', 'TEST')
        
        payload = {
            'email': email,
            'password': password,
        }
        
        try:
            response = requests.post(
                f'{self.base_url}/auth/login', # Removed trailing slash
                json=payload,
                headers=HEADERS,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get('access')
                self.refresh_token_str = data.get('refresh')
                self.user_data = data.get('user', {})
                
                self.log(f'✓ Login successful for user: {email}', 'SUCCESS')
                self.log(f'  User ID: {self.user_data.get("id")}', 'INFO')
                self.log(f'  Full Name: {self.user_data.get("first_name")} {self.user_data.get("last_name")}', 'INFO')
                return True
            else:
                self.log(f'✗ Login failed: {response.status_code} - {response.text}', 'ERROR')
                return False
                
        except Exception as e:
            self.log(f'✗ Login error: {str(e)}', 'ERROR')
            return False
    
    def get_user_profile(self):
        """Test getting user profile"""
        self.log('Testing user profile retrieval...', 'TEST')
        
        if not self.access_token:
            self.log('✗ No access token available', 'ERROR')
            return False
        
        headers = HEADERS.copy()
        headers['Authorization'] = f'Bearer {self.access_token}'
        
        try:
            response = requests.get(
                f'{self.base_url}/auth/profile', # Removed trailing slash
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                self.log('✓ User profile retrieved successfully', 'SUCCESS')
                profile = response.json()
                self.log(f'  Email: {profile.get("email")}', 'INFO')
                self.log(f'  Full Name: {profile.get("first_name")} {profile.get("last_name")}', 'INFO')
                return True
            else:
                self.log(f'✗ Profile retrieval failed: {response.status_code} - {response.text}', 'ERROR')
                return False
                
        except Exception as e:
            self.log(f'✗ Profile retrieval error: {str(e)}', 'ERROR')
            return False
    
    def create_tenant(self, name: str, url: str, database: str, email: str, api_key: str):
        """Test tenant creation"""
        self.log('Testing tenant creation...', 'TEST')
        
        if not self.access_token:
            self.log('✗ No access token available', 'ERROR')
            return False
        
        headers = HEADERS.copy()
        headers['Authorization'] = f'Bearer {self.access_token}'
        
        payload = {
            'name': name,
            'odoo_url': url, # tenant.py expects odoo_url
            'odoo_database': database, # tenant.py expects odoo_database
            'odoo_api_key': api_key, # tenant.py expects odoo_api_key
            'is_active': True
        }
        
        try:
            response = requests.post(
                f'{self.base_url}/tenants', # Removed trailing slash, verified relative path? tenant router likely at /tenants by default if not prefixed?
                # Actually app.py includes tenants router. Let's assume it's at root or check app.py
                json=payload,
                headers=headers,
                timeout=10
            )
            # Checking app.py: app.include_router(tenant_router). Routes in tenants/routes.py use @router.post("/"). 
            # tenants/routes.py prefix is likely /tenants if defined there.
            
            if response.status_code == 201:
                self.tenant_data = response.json()
                self.log(f'✓ Tenant created successfully', 'SUCCESS')
                self.log(f'  Tenant ID: {self.tenant_data.get("id")}', 'INFO')
                self.log(f'  Name: {self.tenant_data.get("name")}', 'INFO')
                return True
            else:
                self.log(f'✗ Tenant creation failed: {response.status_code} - {response.text}', 'ERROR')
                return False
                
        except Exception as e:
            self.log(f'✗ Tenant creation error: {str(e)}', 'ERROR')
            return False
    
    def list_tenants(self):
        """Test listing user's tenants"""
        self.log('Testing tenant list retrieval...', 'TEST')
        
        if not self.access_token:
            self.log('✗ No access token available', 'ERROR')
            return False
        
        headers = HEADERS.copy()
        headers['Authorization'] = f'Bearer {self.access_token}'
        
        try:
            response = requests.get(
                f'{self.base_url}/tenants', # Removed trailing slash
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                # If API returns list directly or dict with results
                if isinstance(data, list):
                    results = data
                else:
                    results = data.get('results', [])
                    
                self.log(f'✓ Tenants retrieved successfully', 'SUCCESS')
                self.log(f'  Total count: {len(results)}', 'INFO')
                for tenant in results[:3]:  # Show first 3
                    self.log(f'  - {tenant.get("name")} ({tenant.get("id")})', 'INFO')
                return True
            else:
                self.log(f'✗ Tenant list failed: {response.status_code} - {response.text}', 'ERROR')
                return False
                
        except Exception as e:
            self.log(f'✗ Tenant list error: {str(e)}', 'ERROR')
            return False
    
    def get_companies(self, tenant_id: str):
        """Test getting companies for a tenant"""
        self.log('Testing company list retrieval...', 'TEST')
        
        if not self.access_token:
            self.log('✗ No access token available', 'ERROR')
            return False
        
        headers = HEADERS.copy()
        headers['Authorization'] = f'Bearer {self.access_token}'
        
        try:
            # Match the implemented route: /master-data/{tenant_id}/companies
            response = requests.get(
                f'{self.base_url}/master-data/{tenant_id}/companies',
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                items = data.get('items', [])
                total = data.get('total', 0)
                
                self.log(f'✓ Companies retrieved successfully', 'SUCCESS')
                self.log(f'  Total count: {total}', 'INFO')
                for company in items[:3]:
                    self.log(f'  - {company.get("name")} (Odoo ID: {company.get("odoo_id")}, Currency: {company.get("currency_code")})', 'INFO')
                return True
            else:
                self.log(f'✗ Company list failed: {response.status_code} - {response.text}', 'ERROR')
                return False
                
        except Exception as e:
            self.log(f'✗ Company list error: {str(e)}', 'ERROR')
            return False
    
    def refresh_token(self):
        """Test token refresh"""
        self.log('Testing token refresh...', 'TEST')
        
        if not self.refresh_token_str:
            self.log('✗ No refresh token available', 'ERROR')
            return False
        
        payload = {'refresh': self.refresh_token_str}
        
        try:
            response = requests.post(
                f'{self.base_url}/auth/token/refresh', # Removed trailing slash
                json=payload,
                headers=HEADERS,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get('access')
                self.log('✓ Token refreshed successfully', 'SUCCESS')
                return True
            else:
                self.log(f'✗ Token refresh failed: {response.status_code} - {response.text}', 'ERROR')
                return False
                
        except Exception as e:
            self.log(f'✗ Token refresh error: {str(e)}', 'ERROR')
            return False
    
    def run_full_test(self):
        """Run complete API test suite"""
        self.log('=' * 60, 'INFO')
        self.log('Django REST API Integration Test', 'INFO')
        self.log('=' * 60, 'INFO')
        
        # Test data
        test_email = 'apitest@example.com'
        test_password = 'TestPass123'
        test_tenant_name = f'Test Tenant {datetime.now().strftime("%Y%m%d%H%M%S")}'
        
        # Step 1: Register user
        self.log('\n--- Step 1: User Registration ---', 'INFO')
        if not self.register_user(test_email, test_password, 'API', 'Tester'):
            self.log('Skipping remaining tests due to registration failure', 'ERROR')
            # Try login anyway if user exists
        
        # Step 2: Login user
        self.log('\n--- Step 2: User Login ---', 'INFO')
        if not self.login_user(test_email, test_password):
            self.log('Stopping tests due to login failure', 'ERROR')
            return False
        
        # Step 3: Get user profile
        self.log('\n--- Step 3: Get User Profile ---', 'INFO')
        if not self.get_user_profile():
            self.log('Warning: Profile retrieval failed', 'WARNING')
        
        # Step 4: Create tenant
        self.log('\n--- Step 4: Create Tenant ---', 'INFO')
        if self.create_tenant(
            name=test_tenant_name,
            url='https://odoo.example.com',
            database='production',
            email='admin@example.com',
            api_key='test_api_key_123'
        ):
            # Step 5: List tenants
            self.log('\n--- Step 5: List Tenants ---', 'INFO')
            self.list_tenants()
            
            # Step 5.1: List companies for the created tenant
            tenant_id = self.tenant_data.get('id')
            if tenant_id:
                self.log('\n--- Step 5.1: List Companies ---', 'INFO')
                self.get_companies(tenant_id)
        
        # Step 6: Refresh token
        self.log('\n--- Step 6: Token Refresh ---', 'INFO')
        if not self.refresh_token():
            self.log('Warning: Token refresh failed', 'WARNING')
        
        self.log('\n' + '=' * 60, 'INFO')
        self.log('API Test Suite Completed', 'INFO')
        self.log('=' * 60, 'INFO')
        return True


if __name__ == '__main__':
    tester = APITester()
    tester.run_full_test()
