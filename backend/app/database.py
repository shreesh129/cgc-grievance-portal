from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event, text
from .config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True, connect_args=connect_args)
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, connection_record):
        cursor=dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
SessionLocal=async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
class Base(DeclarativeBase): pass
async def get_db():
    async with SessionLocal() as db: yield db

async def migrate_schema():
    # Add V5 columns to older V4 databases. Existing V4's overly-restrictive
    # UNIQUE(user_id) constraint cannot be removed safely with a simple ALTER;
    # V5's new installs are constraint-free. Existing demo DBs should be backed
    # up and recreated once when upgrading.
    if not settings.database_url.startswith("sqlite"): return
    async with engine.begin() as conn:
        tables={r[0] for r in (await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))).fetchall()}
        if "users" in tables:
            cols={r[1] for r in (await conn.execute(text("PRAGMA table_info(users)"))).fetchall()}
            additions={"failed_logins":"INTEGER NOT NULL DEFAULT 0","locked_until":"DATETIME"}
            for name,ddl in additions.items():
                if name not in cols: await conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))
