import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config import DATABASE_URL



engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入：每个请求拿一个会话，请求结束自动 commit/rollback"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """启动时建表，import models 触发 Base.metadata 注册"""
    from models import Base
    import models.conversation  # 触发表注册
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)