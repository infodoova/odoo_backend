# Jobs Module

Manages background tasks and scheduled processes, such as data synchronization with Odoo.

## 📁 Structure

- **`sync_job.py`**: Implementation of the Odoo data synchronization task.

## ⚙️ Key Features

- Triggering manual or scheduled syncs.
- Monitoring job status and logs.
- Handling long-running data processing tasks outside the main request cycle.
