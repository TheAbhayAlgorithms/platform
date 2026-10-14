from django.apps import AppConfig
from django.db.backends.signals import connection_created


def configure_sqlite_database(sender, connection, **kwargs):
    """
    Database Hardening for SQLite:
    - Enables foreign key constraint enforcement
    - Sets busy timeout to 5000ms to eliminate locking errors under concurrency
    - Configures WAL (Write-Ahead Logging) journal mode for optimal concurrent reads and writes
    """
    if connection.vendor == 'sqlite':
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("PRAGMA busy_timeout = 5000;")
        # Set journal mode to WAL if not in in-memory test database
        if connection.settings_dict.get('NAME') != ':memory:':
            try:
                cursor.execute("PRAGMA journal_mode = WAL;")
                cursor.execute("PRAGMA synchronous = NORMAL;")
            except Exception:
                pass


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        connection_created.connect(configure_sqlite_database)
