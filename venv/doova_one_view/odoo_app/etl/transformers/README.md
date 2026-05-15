# ETL Transformers

Contains logic for converting raw data from Odoo into the structured format required for our analytics schema.

## 📁 Structure

- **`data_transformer.py`**: Implementation of mapping and transformation rules.

## 🔄 Transformation Logic

- **Denormalization**: Flattening complex Odoo relationships into single rows.
- **Data Cleaning**: Handling null values, date formatting, and type conversions.
- **KPI Pre-calculation**: (When applicable) Pre-computing certain fields to speed up agent queries.
