"""
Side-by-Side Examples: Django vs FastAPI

This file demonstrates how to write the same functionality
in both Django and FastAPI, showing the differences and benefits.
"""

# ============================================================================
# EXAMPLE 1: Creating a User
# ============================================================================

# ─── DJANGO REST Framework (v1) ───────────────────────────────────────────

# odoo_app/api/auth_views.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED, HTTP_400_BAD_REQUEST
from doova_one_view.api.auth.serializers import AppUserCreateSerializer

# Fix missing imports for examples
from odoo_app.models.tenant import Tenant
from odoo_app.etl.orchestrator import ETLOrchestrator
from django.contrib.auth import get_user_model
User = get_user_model()

from rest_framework import serializers
class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = '__all__'

@api_view(['POST'])
@permission_classes([AllowAny])
def register_user(request):
    """
    Django: Register a new user
    
    - Synchronous (blocking)
    - Waits for each operation to complete
    - Can handle ~50 concurrent requests
    """
    serializer = AppUserCreateSerializer(data=request.data)
    
    # Validate input
    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=HTTP_400_BAD_REQUEST
        )
    
    # Save user (blocking operation)
    user = serializer.save()
    
    # Return response
    return Response(
        {
            'id': user.id,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
        },
        status=HTTP_201_CREATED
    )


# ─── FastAPI (v2) ───────────────────────────────────────────────────────

# doova_one_view/fastapi_app.py
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, EmailStr
from datetime import datetime
import asyncio

app = FastAPI()

class UserCreateRequest(BaseModel):
    """Pydantic model for request validation"""
    email: EmailStr
    password: str
    first_name: str
    last_name: str

class UserResponse(BaseModel):
    """Response model"""
    id: int
    email: str
    first_name: str
    last_name: str
    created_at: datetime

@app.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_user_async(user: UserCreateRequest):
    """
    FastAPI: Register a new user asynchronously
    
    - Asynchronous (non-blocking)
    - Can handle other requests while waiting
    - Can handle 500+ concurrent requests
    - Automatic validation with Pydantic
    - Auto-generated OpenAPI docs
    """
    from django.contrib.auth import get_user_model
    
    # User = get_user_model() # Already imported globally for this example file to pass linting
    
    try:
        # Async operation (non-blocking)
        new_user = await asyncio.to_thread(
            User.objects.create_user,
            email=user.email,
            password=user.password,
            first_name=user.first_name,
            last_name=user.last_name
        )
        
        return {
            'id': new_user.id,
            'email': new_user.email,
            'first_name': new_user.first_name,
            'last_name': new_user.last_name,
            'created_at': datetime.now()
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ─── PERFORMANCE COMPARISON ───────────────────────────────────────────────

# Scenario: Process 100 user registrations simultaneously

# Django:
"""
Request 1: [████████████████] 200ms
Request 2: [Waiting for thread...] 200ms
Request 3: [Waiting for thread...] 200ms
...
Total: ~200ms * 100 / 4_threads ≈ 5000ms (5 seconds)
"""

# FastAPI:
"""
Request 1: [██  ] → DB → Continue
Request 2: [██  ] → DB → Continue
Request 3: [██  ] → DB → Continue
...
Total: ~200ms (all concurrent!)
"""

# Result: FastAPI is ~25x faster for I/O-bound operations


# ============================================================================
# EXAMPLE 2: Listing Items with Pagination and Search
# ============================================================================

# ─── DJANGO REST Framework (v1) ───────────────────────────────────────────

from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response

class TenantViewSet(ModelViewSet):
    """Django ViewSet for Tenant CRUD"""
    
    def list(self, request, *args, **kwargs):
        """
        List tenants with pagination and search
        
        Synchronous - blocks during database query
        """
        # Get filter parameters
        search = request.query_params.get('search', '')
        page = int(request.query_params.get('page', 1))
        limit = int(request.query_params.get('limit', 10))
        
        # Build query (synchronous - blocks here)
        query = Tenant.objects.filter(name__icontains=search)
        total = query.count()  # Blocks
        
        # Get page (blocks here)
        tenants = query[(page-1)*limit:page*limit]
        
        # Serialize (blocks here)
        serializer = TenantSerializer(tenants, many=True)
        
        # Return response (finally!)
        return Response({
            'count': total,
            'results': serializer.data
        })


# ─── FastAPI (v2) ───────────────────────────────────────────────────────

from typing import List
from pydantic import BaseModel

class TenantResponse(BaseModel):
    """Tenant response model"""
    id: str
    name: str
    url: str

@app.get(
    "/tenants",
    response_model=List[TenantResponse]
)
async def list_tenants_async(
    search: str = "",
    skip: int = 0,
    limit: int = 10
):
    """
    List tenants with pagination and search
    
    Asynchronous - doesn't block while querying database
    """
    from odoo_app.models import Tenant
    
    async def fetch_tenants():
        # Query filter
        query = Tenant.objects.filter(name__icontains=search)
        
        # Async database operations
        total = await asyncio.to_thread(query.count)
        results = await asyncio.to_thread(
            lambda: list(query[skip:skip + limit])
        )
        
        return results, total
    
    # Non-blocking await
    tenants, total = await fetch_tenants()
    
    return [
        {
            'id': str(t.id),
            'name': t.name,
            'url': t.url
        }
        for t in tenants
    ]


# Performance: Faster response times, more concurrent users


# ============================================================================
# EXAMPLE 3: Parallel Operations (FastAPI Exclusive)
# ============================================================================

# ─── DJANGO: Sequential (Slow) ───────────────────────────────────────────

@api_view(['POST'])
def sync_all_tenants_django(request):
    """
    Sync multiple tenants sequentially in Django
    
    If each sync takes 10 seconds:
    - 10 tenants = 100 seconds total
    """
    tenants = Tenant.objects.all()
    results = []
    
    for tenant in tenants:
        # Sync one by one (blocking)
        orchestrator = ETLOrchestrator(tenant)
        synced, failed = orchestrator.full_sync()  # ← Blocks 10 seconds
        
        results.append({
            'tenant_id': tenant.id,
            'synced': synced,
            'failed': failed
        })
    
    return Response(results)


# ─── FastAPI: Parallel (Fast) ───────────────────────────────────────────

@app.post("/batch/sync-tenants")
async def sync_all_tenants_fastapi():
    """
    Sync multiple tenants in PARALLEL with FastAPI
    
    If each sync takes 10 seconds:
    - 10 tenants = ~10 seconds total (all concurrent!)
    """
    from odoo_app.models import Tenant
    
    async def sync_single(tenant):
        """Sync one tenant asynchronously"""
        orchestrator = ETLOrchestrator(tenant)
        synced, failed = await asyncio.to_thread(
            orchestrator.full_sync
        )
        return {
            'tenant_id': str(tenant.id),
            'synced': synced,
            'failed': failed
        }
    
    tenants = await asyncio.to_thread(
        lambda: list(Tenant.objects.all())
    )
    
    # Run all syncs CONCURRENTLY!
    results = await asyncio.gather(
        *[sync_single(t) for t in tenants]
    )
    
    return results


# Performance: 10-50x faster for parallel operations!


# ============================================================================
# EXAMPLE 4: Auto-Generated Documentation
# ============================================================================

# ─── DJANGO: Manual Documentation ────────────────────────────────────────

"""
POST /api/v1/auth/register/

Request body:
{
  "email": "user@example.com",
  "password": "SecurePass123",
  "password_confirm": "SecurePass123",
  "first_name": "John",
  "last_name": "Doe"
}

Response (201):
{
  "id": 1,
  "email": "user@example.com",
  "first_name": "John",
  "last_name": "Doe"
}

Errors (400):
{
  "password_confirm": ["Passwords don't match"]
}

Note: Must create and maintain this documentation manually!
"""


# ─── FastAPI: Auto-Generated Documentation ───────────────────────────────

"""
Simply visit: http://localhost:8000/api/v2/docs

You get:
✅ Interactive Swagger UI
✅ All endpoints listed
✅ Request/response schemas
✅ "Try it out" button to test
✅ Error responses documented
✅ All generated automatically!

Why?
- Pydantic models define the schema
- FastAPI reads models and generates docs
- No manual documentation needed!
"""


# ============================================================================
# EXAMPLE 5: Request Validation
# ============================================================================

# ─── DJANGO: Manual Validation ───────────────────────────────────────────

from rest_framework import serializers

class AppUserCreateSerializer(serializers.Serializer):
    """Manual validation with serializers"""
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    password_confirm = serializers.CharField(write_only=True)
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    
    def validate(self, data):
        """Manual validation logic"""
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError(
                "Passwords don't match"
            )
        
        # Manual email uniqueness check
        if User.objects.filter(email=data['email']).exists():
            raise serializers.ValidationError(
                "Email already registered"
            )
        
        return data


# ─── FastAPI: Automatic Validation ───────────────────────────────────────

from pydantic import BaseModel, EmailStr, field_validator

class UserCreateRequest(BaseModel):
    """Automatic validation with Pydantic"""
    email: EmailStr  # ← Auto validates email format!
    password: str    # ← Required field
    first_name: str
    last_name: str
    
    @field_validator('email')
    @classmethod
    def validate_email_unique(cls, v):
        """Custom validation if needed"""
        if User.objects.filter(email=v).exists():
            raise ValueError('Email already registered')
        return v
    
    @field_validator('password')
    @classmethod
    def validate_password_strength(cls, v):
        """Password strength validation"""
        if len(v) < 8:
            raise ValueError('Password must be 8+ characters')
        return v


# Benefit: Less boilerplate, automatic validation, better error messages


# ============================================================================
# EXAMPLE 6: Error Handling
# ============================================================================

# ─── DJANGO: Manual Error Handling ───────────────────────────────────────

@api_view(['GET'])
def get_tenant_django(request, pk):
    """Get tenant - manual error handling"""
    try:
        tenant = Tenant.objects.get(id=pk)
    except Tenant.DoesNotExist:
        return Response(
            {'detail': 'Tenant not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
    serializer = TenantSerializer(tenant)
    return Response(serializer.data)


# ─── FastAPI: Automatic Error Handling ───────────────────────────────────

@app.get("/tenants/{tenant_id}")
async def get_tenant_fastapi(tenant_id: str):
    """Get tenant - automatic error handling"""
    from odoo_app.models import Tenant
    
    try:
        tenant = await asyncio.to_thread(
            Tenant.objects.get,
            id=tenant_id
        )
        return tenant
    except Tenant.DoesNotExist:
        # FastAPI automatically converts to JSON
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )
    # Other exceptions automatically return 500


# Benefit: Cleaner code, consistent error format, HTTP compliance


# ============================================================================
# SUMMARY TABLE
# ============================================================================

"""
┌─────────────────────┬──────────────────────┬──────────────────────┐
│      Feature        │      Django DRF      │       FastAPI        │
├─────────────────────┼──────────────────────┼──────────────────────┤
│ Concurrency Model   │ Threading            │ Async/Await          │
│ Performance         │ ~50 req/sec          │ ~500+ req/sec        │
│ Parallelism         │ Sequential           │ Concurrent           │
│ Validation          │ Manual serializers   │ Pydantic models      │
│ Documentation       │ Manual (DRF docs)    │ Auto-generated       │
│ Error Handling      │ Manual               │ Automatic            │
│ Learning Curve      │ Moderate             │ Very easy            │
│ Database ORM        │ Django ORM           │ asyncio.to_thread()  │
│ Admin Interface     │ Built-in             │ Not available        │
│ Maturity            │ Excellent            │ Good                 │
└─────────────────────┴──────────────────────┴──────────────────────┘

RECOMMENDATION:
- Use Django for: Admin, traditional endpoints, established code
- Use FastAPI for: High-traffic endpoints, new features, APIs
- Use BOTH together with ASGI mounting!
"""
