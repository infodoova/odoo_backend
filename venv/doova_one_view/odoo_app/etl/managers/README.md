# ETL Managers

Responsible for managing the infrastructure and orchestration of the data flow.

## 📁 Structure

- **`database_manager.py`**: Handles database-level operations during the ETL process, such as upserting records into the local analytics tables and managing transaction boundaries.

## ⚙️ Key Features

- **Efficient Upserts**: Logic to update existing records or insert new ones based on Odoo IDs.
- **Tenant Context**: Ensures data is always associated with the correct tenant during the load phase.
- **Error Handling**: Transaction management to prevent partial or corrupted data loads.
