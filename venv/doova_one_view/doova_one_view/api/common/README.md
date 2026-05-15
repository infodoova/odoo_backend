# Common Module

Provides shared utilities, base schemas, and error handling mechanisms used across all API modules.

## 📁 Structure

- **`exceptions.py`**: Custom exception classes for consistent error reporting.
- **`handlers.py`**: FastAPI exception handlers for converting exceptions into HTTP responses.
- **`responses.py`**: Standardized response formats.
- **`schemas.py`**: Shared Pydantic models (e.g., pagination, generic success/error).
- **`utils.py`**: Helper functions for common tasks like data formatting and logging.

## 🛠 Usage

This module is not intended to be accessed directly via endpoints but serves as a foundation for other modules to ensure consistency and reduce code duplication.
