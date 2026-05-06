import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from contextlib import contextmanager


class DataCatalog:
    """SQLite-backed catalog for tracking downloaded market data."""
    
    def __init__(self, db_path: str = "data/market_data.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_tables()
    
    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    def _init_tables(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS data_registry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    mt5_symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    rows_count INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    file_size_bytes INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(symbol, timeframe)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS download_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    requested_start TEXT,
                    requested_end TEXT,
                    returned_rows INTEGER,
                    status TEXT NOT NULL,
                    message TEXT,
                    timestamp TEXT NOT NULL
                )
            """)
    
    def register(
        self,
        symbol: str,
        mt5_symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str,
        rows_count: int,
        file_path: str,
        file_size_bytes: Optional[int] = None
    ):
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO data_registry 
                (symbol, mt5_symbol, timeframe, start_date, end_date, rows_count, 
                 file_path, file_size_bytes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timeframe) DO UPDATE SET
                    mt5_symbol=excluded.mt5_symbol,
                    start_date=excluded.start_date,
                    end_date=excluded.end_date,
                    rows_count=excluded.rows_count,
                    file_path=excluded.file_path,
                    file_size_bytes=excluded.file_size_bytes,
                    updated_at=excluded.updated_at
            """, (symbol, mt5_symbol, timeframe, start_date, end_date, rows_count,
                  file_path, file_size_bytes, now, now))
    
    def log_download(
        self,
        symbol: str,
        timeframe: str,
        requested_start: Optional[str],
        requested_end: Optional[str],
        returned_rows: int,
        status: str,
        message: Optional[str] = None
    ):
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO download_log 
                (symbol, timeframe, requested_start, requested_end, returned_rows, status, message, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (symbol, timeframe, requested_start, requested_end, returned_rows, status, message, now))
    
    def get_registry(self, symbol: Optional[str] = None, timeframe: Optional[str] = None) -> List[Dict]:
        query = "SELECT * FROM data_registry WHERE 1=1"
        params = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if timeframe:
            query += " AND timeframe = ?"
            params.append(timeframe)
        query += " ORDER BY symbol, timeframe"
        
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
    
    def get_coverage(self, symbol: str, timeframe: str) -> Optional[Dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM data_registry WHERE symbol = ? AND timeframe = ?",
                (symbol, timeframe)
            ).fetchone()
            return dict(row) if row else None
    
    def list_available_symbols(self) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT DISTINCT symbol FROM data_registry ORDER BY symbol").fetchall()
            return [r[0] for r in rows]
