# Tenants Module

Manages multi-tenancy configurations, Odoo connection settings, and tenant-specific metadata.

## 📁 Structure

- **`routes.py`**: Endpoints for tenant management and Odoo setup.
- **`schemas.py`**: Models for tenant configuration and Odoo credentials.
- **`service.py`**: Logic for validating Odoo connections and managing tenant data.

## 🏢 Key Features

- Multi-tenant isolation.
- Odoo API connection management (URL, DB, Username, Password).
- Tenant-specific feature flags and configurations.
