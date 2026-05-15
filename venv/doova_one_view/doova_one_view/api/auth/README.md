# Authentication Module

Handles user authentication, authorization, and session management for the Doova OneView platform.

## 📁 Structure

- **`routes.py`**: Endpoints for login, logout, and token management.
- **`service.py`**: Logic for user validation, password hashing, and token generation.
- **`schemas.py`**: Data models for credentials and tokens.
- **`permissions.py`**: Role-based access control (RBAC) and permission checks.
- **`dependencies.py`**: FastAPI dependencies for securing routes.

## 🔐 Key Features

- JWT-based authentication.
- Password encryption and verification.
- Token refresh mechanisms.
- User session tracking.
