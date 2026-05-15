# Odoo App Models: Schema Documentation

This directory contains the Django model definitions that power the Doova platform.

## 📊 Model Categories

1. **Agent Models (`agent.py`)**:
   - `ChatSession`: Persistent chat threads with memory summaries and plan states.
   - `ChatMessage`: Individual messages with metadata (role, payload, message type).

2. **Analytics Schema (`fact_` and `dim_`)**:
   - We follow a Star Schema approach for analytics.
   - **Fact Tables**: Transactional data (e.g., `FactSalesOrder`, `FactStockMove`, `FactJournalItem`).
   - **Dimension Tables**: Master data (e.g., `DimProduct`, `DimCustomer`, `DimAccount`).

3. **Core Infrastructure**:
   - `Tenant`: Configuration for Odoo connections and company mapping.
   - `SyncLog`: Tracking the status of ETL processes.

## 🔑 Key Principles

- **Tenant Isolation**: All analytics tables MUST have a `tenant_id` field.
- **Index Optimization**: Common filter fields (tenant_id, date, company_id) are indexed for high-speed agent queries.
- **Normalization**: While Odoo is highly normalized, our models are intentionally denormalized to reduce join complexity for the SQL Agent.
