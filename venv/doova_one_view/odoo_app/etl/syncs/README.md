# ETL Synchronizers

This directory contains the domain-specific logic for synchronizing different types of data from Odoo to the local database.

## 📂 Synchronizer Types

- **`base_synchronizer.py`**: The abstract base class providing common logic for all synchronizers (e.g., logging, basic Odoo fetching).
- **`accounting_synchronizer.py`**: Syncs journal entries, moves, and accounting periods.
- **`sales_synchronizer.py`**: Handles sales orders, quotations, and order lines.
- **`purchase_synchronizer.py`**: Syncs purchase orders and procurement data.
- **`inventory_synchronizer.py`**: Tracks products, stock quants, moves, and pickings.
- **`master_data` (Company, Partner, Currency, User)**: Syncs core entities required for relationships in fact tables.
- **`time_synchronizer.py`**: Populates the time dimension table for advanced temporal analytics.

## 🔄 Sync Workflow

1. Fetch modified records from Odoo since the last successful sync.
2. Transform Odoo's nested structures into our flattened analytics schema.
3. Batch upsert the data into the local PostgreSQL database.
