# ETL Clients

Contains communication clients for interacting with external services, primarily Odoo.

## 📁 Structure

- **`odoo_client.py`**: A robust wrapper around the Odoo XML-RPC API. It handles authentication, connection pooling, and provides high-level methods for searching and reading Odoo records.

## 🛠 Key Features

- **XML-RPC Integration**: Communicates with Odoo's `common` and `object` endpoints.
- **Connection Management**: Safely handles Odoo session timeouts and reconnections.
- **Data Retrieval**: Optimized methods for batch fetching records using domain filters.
