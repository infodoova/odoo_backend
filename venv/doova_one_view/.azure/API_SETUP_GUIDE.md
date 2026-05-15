# REST API Setup Guide

## Overview
The Django REST API is now fully configured with JWT authentication and integrated into the main project.

## Configuration Files Updated

### 1. Django Settings (`doova_one_view/settings.py`)
- **Added INSTALLED_APPS**: `rest_framework` and `rest_framework_simplejwt`
- **REST_FRAMEWORK Configuration**:
  - JWT authentication enabled by default
  - Token-based permissions required
  - Pagination: 10 items per page
  - Throttling: 100/hour for anonymous, 1000/hour for authenticated users
  
- **JWT Configuration**:
  - Access token lifetime: 1 hour
  - Refresh token lifetime: 7 days
  - Token rotation enabled
  - Automatic blacklist after rotation

### 2. Main URLs (`doova_one_view/urls.py`)
- Added API routing: `path('api/', include('odoo_app.api.urls'))`
- All API endpoints accessible at `/api/*`

## API Endpoints

### Authentication
- `POST /api/auth/login/` - Obtain JWT tokens (email/password)
- `POST /api/auth/token/refresh/` - Refresh access token
- `POST /api/auth/register/` - Register new user
- `GET /api/auth/profile/` - Get current user profile
- `PUT/PATCH /api/auth/profile/update/` - Update user profile
- `POST /api/auth/change-password/` - Change user password

### Tenants (CRUD + Sync Actions)
- `GET /api/tenants/` - List user's tenants
- `POST /api/tenants/` - Create new tenant
- `GET /api/tenants/{id}/` - Get tenant details
- `PUT/PATCH /api/tenants/{id}/` - Update tenant
- `DELETE /api/tenants/{id}/` - Delete tenant
- `POST /api/tenants/{id}/sync/` - Full sync from Odoo
- `POST /api/tenants/{id}/delta-sync/` - Incremental sync
- `GET /api/tenants/{id}/status/` - Get last sync status

## Authentication Flow

### 1. User Registration
```bash
curl -X POST http://localhost:8000/api/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "SecurePass123",
    "password_confirm": "SecurePass123",
    "first_name": "John",
    "last_name": "Doe"
  }'
```

### 2. Login (Obtain Tokens)
```bash
curl -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "SecurePass123"
  }'
```

Response:
```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "user": {
    "id": 1,
    "email": "user@example.com",
    "first_name": "John",
    "last_name": "Doe"
  }
}
```

### 3. Use Access Token
```bash
curl -X GET http://localhost:8000/api/tenants/ \
  -H "Authorization: Bearer <access_token>"
```

### 4. Refresh Token (When Expired)
```bash
curl -X POST http://localhost:8000/api/auth/token/refresh/ \
  -H "Content-Type: application/json" \
  -d '{
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
  }'
```

## API File Structure

```
odoo_app/api/
├── __init__.py              # Package exports
├── serializers.py           # Data serialization (5 classes)
├── permissions.py           # Access control (6 permission classes)
├── auth_views.py            # Authentication endpoints
├── tenant_views.py          # Tenant CRUD + sync endpoints
└── urls.py                  # Route configuration
```

## Permission Classes

1. **IsAuthenticated** - User must be logged in
2. **IsTenantOwnerOrAdmin** - Owner/Admin of tenant only
3. **IsOwner** - Object owner only
4. **CanManageTenant** - Owner/Manager role + tenant access
5. **CanViewTenant** - View-only tenant access
6. **IsOwnerOrReadOnly** - Permissive read, owner-only write

## Database Integration

- Tenants are automatically filtered by user's `UserTenantAccess` records
- Only tenants where user has access are returned in list views
- User creation automatically creates admin access to their own tenant

## Security Features

1. **JWT Tokens**
   - HS256 signing algorithm
   - HTTP-only cookie storage recommended (frontend)
   - Token rotation prevents replay attacks

2. **Permissions**
   - Tenant-level isolation
   - Role-based access control
   - Object-level access verification

3. **Rate Limiting**
   - Anonymous: 100 requests/hour
   - Authenticated: 1000 requests/hour

4. **CORS** (Ready to configure)
   - Add `django-cors-headers` for cross-origin requests
   - Configure CORS_ALLOWED_ORIGINS in settings

## Testing the API

### Start Django Development Server
```bash
python manage.py runserver
```

### Test User Registration
```bash
curl -X POST http://localhost:8000/api/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "TestPass123",
    "password_confirm": "TestPass123",
    "first_name": "Test",
    "last_name": "User"
  }'
```

### Test Login
```bash
curl -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "TestPass123"
  }'
```

### Save Token
```bash
# Copy the "access" token from login response
export TOKEN="your_access_token_here"
```

### Test Tenant List
```bash
curl -X GET http://localhost:8000/api/tenants/ \
  -H "Authorization: Bearer $TOKEN"
```

### Create Tenant
```bash
curl -X POST http://localhost:8000/api/tenants/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Tenant",
    "url": "https://odoo.example.com",
    "database": "production",
    "email": "admin@example.com",
    "api_key": "test_api_key_123"
  }'
```

### Trigger Full Sync
```bash
curl -X POST http://localhost:8000/api/tenants/{tenant_id}/sync/ \
  -H "Authorization: Bearer $TOKEN"
```

## Next Steps

1. **Frontend Integration**
   - Implement login/register forms
   - Store JWT tokens securely
   - Include auth header in API requests

2. **Database Security**
   - Implement API key encryption for stored Odoo credentials
   - Use Fernet encryption from cryptography library

3. **User Management**
   - Create UserTenantAccessViewSet for managing access grants
   - Allow tenant owners to invite users

4. **Monitoring**
   - Set up request logging
   - Monitor sync operations via status endpoint
   - Alert on failed syncs

5. **Production Deployment**
   - Configure CORS_ALLOWED_ORIGINS
   - Use environment variables for SECRET_KEY
   - Enable HTTPS only
   - Configure proper ALLOWED_HOSTS
   - Use Gunicorn/uWSGI for production

## Troubleshooting

### Token Expired
- Get new access token using refresh endpoint
- Refresh token lasts 7 days

### Permission Denied
- Verify user has access to tenant (UserTenantAccess record)
- Check user role (owner/manager/viewer)
- Confirm token is valid

### Sync Failed
- Check Odoo credentials in tenant settings
- Verify Odoo URL is accessible
- Check logs: `tail -f logs/etl.log`

## Environment Variables (Production)

```bash
DEBUG=False
SECRET_KEY=your-secret-key
ALLOWED_HOSTS=yourdomain.com
DB_NAME=Unified
DB_USER=postgres
DB_PASSWORD=secure_password
DB_HOST=localhost
DB_PORT=5433
ODOO_USERNAME=your_email@company.com
ODOO_API_KEY=your_api_key
```

## API Documentation

Full API documentation available at:
- Swagger UI: `/api/swagger/` (requires drf-spectacular)
- ReDoc: `/api/redoc/` (requires drf-spectacular)

To enable Swagger documentation, install:
```bash
pip install drf-spectacular
```

Then add to INSTALLED_APPS:
```python
'drf_spectacular',
```
