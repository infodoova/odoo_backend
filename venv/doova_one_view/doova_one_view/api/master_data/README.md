# Master Data Module

Manages core business entities that are shared across different modules, such as Partners (Customers/Vendors), Companies, Currencies, Products, and Lots/Serial Numbers.

## 📁 Structure

- **`routes.py`**: Endpoints for listing, exporting, searching, and obtaining filters for partners, products, companies, lots, and currencies.
- **`schemas.py`**: Pydantic models for core entities and searches.
- **`service.py`**: Business logic, Star Schema mappings, and query filters.

## 🔑 Key Features

- **Company & Currency Management**: Multi-company setup with currency symbols, codes, and automatic Odoo sync mappings.
- **Partner Profiles**: Listing, searching, and exporting customers and suppliers.
- **Product Dimension**: Complete search and export capabilities along with dedicated category hierarchical tree rendering.
- **Lot / Serial Numbers**: Tracking expiration, use, removal, and alert dates per lot.
- **Advanced Dynamic Filters**:
  - `GET /{tenant_id}/filters`: Shared filters across all entities.
  - `GET /{tenant_id}/products/filters`: Dedicated, fast filtering for the Product list/search.
  - `GET /{tenant_id}/partners/filters`: Distinct filters specifically for Partners.
  - `GET /{tenant_id}/lots/filters`: Distinct filters for Lot tracking.
