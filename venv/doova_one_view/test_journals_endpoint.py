import requests
from datetime import datetime

API_BASE_URL = 'http://localhost:8000/api/v1'
HEADERS = {'Content-Type': 'application/json'}

def test_journals_endpoint():
    # 1. Register/Login
    email = 'apitest@example.com'
    password = 'TestPass123'
    
    # Try to login first
    login_resp = requests.post(
        f'{API_BASE_URL}/auth/login',
        json={'email': email, 'password': password},
        headers=HEADERS
    )
    
    if login_resp.status_code != 200:
        print("Login failed, trying to register...")
        reg_resp = requests.post(
            f'{API_BASE_URL}/auth/register',
            json={
                'email': email,
                'password': password,
                'password_confirm': password,
                'first_name': 'Test',
                'last_name': 'User',
                'role': 'owner'
            },
            headers=HEADERS
        )
        if reg_resp.status_code not in (200, 201, 400):
            print(f"Registration failed: {reg_resp.text}")
            return
            
        login_resp = requests.post(
            f'{API_BASE_URL}/auth/login',
            json={'email': email, 'password': password},
            headers=HEADERS
        )
        if login_resp.status_code != 200:
            print(f"Login failed after registration: {login_resp.text}")
            return

    token = login_resp.json().get('access')
    print("Successfully logged in.")
    auth_headers = {**HEADERS, 'Authorization': f'Bearer {token}'}

    # 2. Get Tenants
    tenants_resp = requests.get(
        f'{API_BASE_URL}/tenants',
        headers=auth_headers
    )
    if tenants_resp.status_code != 200:
        print(f"Failed to get tenants: {tenants_resp.text}")
        return
        
    tenants = tenants_resp.json()
    if isinstance(tenants, dict):
        tenants = tenants.get('results', [])
        
    if not tenants:
        print("No tenants found. Creating one...")
        tenant_resp = requests.post(
            f'{API_BASE_URL}/tenants',
            json={
                'name': 'Test Tenant',
                'odoo_url': 'https://odoo.example.com',
                'odoo_database': 'production',
                'odoo_api_key': 'test_api_key_123',
                'is_active': True
            },
            headers=auth_headers
        )
        if tenant_resp.status_code != 201:
            print(f"Failed to create tenant: {tenant_resp.text}")
            return
        tenant_id = tenant_resp.json().get('id')
    else:
        tenant_id = tenants[0].get('id')

    print(f"Using tenant ID: {tenant_id}")

    # 3. Test the journals endpoint
    print(f"\nTesting /accounting/{tenant_id}/dashboard/journals")
    journals_resp = requests.get(
        f'{API_BASE_URL}/accounting/{tenant_id}/dashboard/journals',
        headers=auth_headers
    )
    
    print(f"Status Code: {journals_resp.status_code}")
    if journals_resp.status_code == 200:
        import json
        print("Response JSON:")
        print(json.dumps(journals_resp.json(), indent=2))
    else:
        print(f"Error Response: {journals_resp.text}")

if __name__ == '__main__':
    test_journals_endpoint()
