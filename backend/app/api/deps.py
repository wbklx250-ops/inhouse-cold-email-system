from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.services.cloudflare import CloudflareService


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Async generator that yields a database session.
    Ensures proper cleanup in finally block.
    """
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def get_cloudflare_service() -> CloudflareService:
    """
    Returns a CloudflareService instance.
    """
    return CloudflareService()