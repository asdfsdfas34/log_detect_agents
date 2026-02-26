"""Compatibility shim: PostgreSQL module now delegates to SQLite backend."""

from app.db.sqlite_store import fetch_recent_logs

__all__ = ["fetch_recent_logs"]
