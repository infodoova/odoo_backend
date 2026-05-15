"""
Time dimension synchronizer
"""

import logging
from datetime import datetime, timedelta
from typing import Tuple
from odoo_app.etl.syncs.base_synchronizer import BaseSynchronizer

logger = logging.getLogger(__name__)


class TimeDimensionSynchronizer(BaseSynchronizer):
    """Populates dim_time with a range of dates for analysis"""

    def sync(self, tenant_id: str, **kwargs) -> Tuple[int, int]:
        logger.info("Populating time dimension...")
        
        # Determine range (default: 2010 to current year + 10)
        start_date = datetime(2010, 1, 1)
        end_date = datetime(datetime.now().year + 11, 1, 1) - timedelta(days=1)
        
        synced, failed = 0, 0
        current = start_date
        
        try:
            while current <= end_date:
                try:
                    date_id = int(current.strftime('%Y%m%d'))
                    query = """
                        INSERT INTO dim_time (
                            date_id, full_date, year, quarter, month, month_name,
                            week, day_of_month, day_of_week, day_name,
                            is_weekend, is_holiday
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (date_id) DO NOTHING
                    """
                    
                    self.db.execute(query, (
                        date_id,
                        current.date(),
                        current.year,
                        (current.month - 1) // 3 + 1,
                        current.month,
                        current.strftime('%B'),
                        current.isocalendar()[1],
                        current.day,
                        current.isoweekday(),
                        current.strftime('%A'),
                        current.isoweekday() in [6, 7],
                        False
                    ))
                    
                    synced += 1
                except Exception as e:
                    logger.warning(f"Failed to insert date {current}: {e}")
                    failed += 1
                
                current += timedelta(days=1)
            
            self.db.conn.commit()
            logger.info(f"Populated {synced} dates in dim_time")
            return synced, failed
            
        except Exception as e:
            logger.error(f"Time dimension sync failed: {e}")
            raise
