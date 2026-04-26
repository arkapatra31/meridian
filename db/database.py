import logging
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from db.entities import Base

logger = logging.getLogger("meridian.db")

DB_DIR = Path(__file__).resolve().parent
DB_PATH = DB_DIR / "meridian.db"
DB_URL = f"sqlite:///{DB_PATH}"

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _build_engine(url: str = DB_URL) -> Engine:
    engine = create_engine(url, echo=False, future=True)

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def init_db(db_path: Path = DB_PATH) -> Engine:
    """Create the SQLite file (if absent) and ensure all tables exist."""
    global _engine, _SessionLocal

    db_path.parent.mkdir(parents=True, exist_ok=True)
    existed = db_path.exists()

    _engine = _build_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)

    logger.info("[db] %s database at %s", "opened existing" if existed else "created new", db_path)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        return init_db()
    return _engine


def get_session() -> Session:
    if _SessionLocal is None:
        init_db()
    assert _SessionLocal is not None
    return _SessionLocal()


def dispose() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


if __name__ == "__main__":
    init_db()
