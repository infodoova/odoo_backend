"""
PostgreSQL Database Manager
Handles all database connections and operations
"""

import psycopg2
from psycopg2.extras import execute_batch
import logging
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages PostgreSQL connections and queries"""
    
    def __init__(self, connection_string: str):
        self.conn_string = connection_string
        self.conn = None
        self.cursor = None
    
    def connect(self) -> None:
        """Establish database connection"""
        self.conn = psycopg2.connect(self.conn_string)
        self.cursor = self.conn.cursor()
        logger.info("Connected to PostgreSQL")
    
    def close(self) -> None:
        """Close database connection"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("Closed PostgreSQL connection")
    
    def execute(self, query: str, params: tuple = None) -> None:
        """Execute a query without returning results"""
        try:
            self.cursor.execute(query, params)
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Query execution failed: {e}")
            raise
    
    def fetch_one(self, query: str, params: tuple = None) -> Optional[tuple]:
        """Execute query and fetch one result"""
        try:
            self.cursor.execute(query, params)
            return self.cursor.fetchone()
        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            raise
    
    def fetch_all(self, query: str, params: tuple = None) -> List[tuple]:
        """Execute query and fetch all results"""
        try:
            self.cursor.execute(query, params)
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            raise
    
    def execute_batch(self, query: str, params_list: List[tuple], page_size: int = 100) -> None:
        """Execute multiple queries in batch"""
        try:
            execute_batch(self.cursor, query, params_list, page_size=page_size)
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Batch execution failed: {e}")
            raise
    
    def get_last_sync_time(self, tenant_id: str, entity_type: str) -> Optional[str]:
        """Get last successful sync timestamp"""
        query = """
            SELECT MAX(completed_at)::text
            FROM sync_logs
            WHERE tenant_id = %s 
              AND entity_type = %s 
              AND status = 'completed'
        """
        result = self.fetch_one(query, (tenant_id, entity_type))
        return result[0] if result and result[0] else None
    
    def log_sync_start(self, tenant_id: str, entity_type: str, sync_type: str) -> int:
        """Log sync job start and return log ID"""
        query = """
            INSERT INTO sync_logs (tenant_id, entity_type, sync_type, status, records_synced, records_failed, started_at)
            VALUES (%s, %s, %s, 'running', 0, 0, NOW())
            RETURNING id
        """
        result = self.fetch_one(query, (tenant_id, entity_type, sync_type))
        self.conn.commit()
        return result[0] if result else None
    
    def log_sync_completion(
        self, 
        log_id: int, 
        records_synced: int, 
        records_failed: int,
        status: str = 'completed',
        error_message: str = None
    ) -> None:
        """Update sync log with completion status"""
        query = """
            UPDATE sync_logs
            SET status = %s,
                records_synced = %s,
                records_failed = %s,
                error_message = %s,
                completed_at = NOW()
            WHERE id = %s
        """
        self.execute(query, (
            status, records_synced, records_failed, error_message, log_id
        ))
