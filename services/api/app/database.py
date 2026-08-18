from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from .config import settings

# pool_pre_ping evita usar conexiones muertas tras un restart de Postgres
engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=5, max_overflow=10)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """Dependency de FastAPI: una sesión de DB por request, cerrada al final."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
