# Odoo App: Core Business Logic and Data Layer

This directory contains the Django-based core of the Doova platform. It defines the database schema, handles data synchronization with Odoo, and provides the primary data models.

## 📂 Module Breakdown

- **`models/`**: Defines the database tables for multi-tenancy, chat sessions, Odoo sync logs, and denormalized "fact" and "dim" tables for analytics.
- **`etl/`**: (Extract, Transform, Load) Contains the scripts and logic responsible for pulling data from Odoo's XML-RPC API and populating the local PostgreSQL analytics tables.
- **`migrations/`**: Standard Django database migration files.
- **`admin.py`**: Configuration for the Django Admin interface to manage users and tenants.

## 🗄 Data Strategy

Doova uses a "Local Mirror" strategy for maximum performance:
1. Data is extracted from Odoo.
2. It is transformed into a denormalized schema optimized for financial queries.
3. It is stored in local PostgreSQL tables (prefixed with `fact_` and `dim_`).
4. The AI Agent and API query these local tables instead of making live XML-RPC calls to Odoo.
