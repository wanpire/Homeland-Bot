from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url, pool_pre_ping=True, pool_size=20, max_overflow=20, pool_timeout=5
)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
