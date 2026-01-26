"""
Database session configuration for Neon Serverless PostgreSQL.

Neon is a serverless PostgreSQL provider with specific connection requirements:
- SSL is required (handled via ssl context in connect_args)
- Connection pooling is important due to connection limits on free tier
- pool_pre_ping ensures connections are valid before use (serverless cold start)
- Retry logic handles transient connection drops in serverless environments
"""
import ssl
import asyncio
import logging
from collections.abc import AsyncGenerator
from functools import wraps
from typing import TypeVar, Callable, Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.exc import DBAPIError, OperationalError

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Type variable for retry decorator
T = TypeVar('T')


def prepare_database_url(url: str) -> tuple[str, dict]:
    """
    Prepare database URL for asyncpg.
    
    asyncpg doesn't accept sslmode as a query parameter - it needs SSL
    configured via connect_args. This function strips sslmode from the URL
    and returns the appropriate connect_args.
    
    Returns:
        tuple: (cleaned_url, connect_args)
    """
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    
    # Check if SSL is required
    ssl_required = False
    if "sslmode" in query_params:
        sslmode = query_params.pop("sslmode")[0]
        ssl_required = sslmode in ("require", "verify-ca", "verify-full")
    if "ssl" in query_params:
        ssl_val = query_params.pop("ssl")[0]
        ssl_required = ssl_val.lower() in ("true", "1", "require")
    
    # Rebuild URL without SSL params
    new_query = urlencode(query_params, doseq=True)
    cleaned_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment,
    ))
    
    # Build connect_args
    connect_args = {}
    if ssl_required:
        # Create SSL context for Neon connections
        ssl_context = ssl.create_default_context()
        connect_args["ssl"] = ssl_context
    
    return cleaned_url, connect_args


# Prepare the database URL and connect_args
database_url, connect_args = prepare_database_url(settings.database_url)

# Create async engine with Neon-optimized settings
# CRITICAL: Neon free tier has ~10 max connections
# Increased pool size to handle parallel browser tasks + API requests + background jobs
engine = create_async_engine(
    database_url,
    echo=settings.debug,
    # Connection pool settings optimized for Neon serverless
    pool_pre_ping=True,    # Check connection health before using (handles cold starts)
    pool_size=5,           # Increased from 3 - handles parallel automation better
    max_overflow=5,        # Increased from 2 (total max: 10 connections = Neon limit)
    pool_timeout=60,       # Increased from 30 - give more time during high load
    pool_recycle=180,      # Reduced from 300 - serverless can drop connections faster
    pool_reset_on_return='rollback',  # Clean connection state on return to pool
    connect_args=connect_args,
)


def is_connection_error(error: Exception) -> bool:
    """Check if an exception is a transient connection error that can be retried."""
    error_str = str(error).lower()
    connection_error_indicators = [
        'connection was closed',
        'connection does not exist',
        'connection reset',
        'connection refused',
        'connection timed out',
        'server closed the connection',
        'cannot allocate connection',
        'lost connection',
        'connection pool',
        'connectiondoesnotexisterror',
        'interfaceerror',
    ]
    return any(indicator in error_str for indicator in connection_error_indicators)


async def execute_with_retry(
    session: AsyncSession,
    operation: Callable[[], Any],
    max_retries: int = 3,
    retry_delay: float = 0.5
) -> Any:
    """
    Execute a database operation with retry logic for transient connection errors.
    
    Args:
        session: The database session
        operation: An async callable that performs the database operation
        max_retries: Maximum number of retry attempts
        retry_delay: Base delay between retries (doubles each retry)
        
    Returns:
        The result of the operation
        
    Raises:
        The last exception if all retries fail
    """
    last_error = None
    
    for attempt in range(max_retries + 1):
        try:
            return await operation()
        except (DBAPIError, OperationalError) as e:
            last_error = e
            if is_connection_error(e) and attempt < max_retries:
                delay = retry_delay * (2 ** attempt)  # Exponential backoff
                logger.warning(
                    f"Database connection error (attempt {attempt + 1}/{max_retries + 1}), "
                    f"retrying in {delay}s: {e}"
                )
                await asyncio.sleep(delay)
                # Try to invalidate the connection for the session
                try:
                    await session.rollback()
                except Exception:
                    pass  # Ignore rollback errors on bad connection
            else:
                raise
        except Exception as e:
            # Check if the underlying cause is a connection error
            if is_connection_error(e) and attempt < max_retries:
                delay = retry_delay * (2 ** attempt)
                logger.warning(
                    f"Database connection error (attempt {attempt + 1}/{max_retries + 1}), "
                    f"retrying in {delay}s: {e}"
                )
                await asyncio.sleep(delay)
                try:
                    await session.rollback()
                except Exception:
                    pass
            else:
                raise
    
    raise last_error

# Alias for clarity - this IS an async engine, use this in background tasks
async_engine = engine

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that provides a database session.
    
    Usage:
        @router.get("/")
        async def endpoint(db: AsyncSession = Depends(get_db_session)):
            ...
    """
    async with SessionLocal() as session:
        yield session


class RetryableSession:
    """
    A wrapper around AsyncSession that automatically retries on connection errors.
    
    This is useful for endpoints that make multiple sequential queries where
    a serverless database connection might drop between queries.
    """
    
    def __init__(self, session_factory: async_sessionmaker, max_retries: int = 3):
        self._session_factory = session_factory
        self._max_retries = max_retries
        self._session: AsyncSession | None = None
    
    async def __aenter__(self) -> 'RetryableSession':
        self._session = self._session_factory()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()
    
    async def _get_fresh_session(self):
        """Get a fresh session, closing the old one if exists."""
        if self._session:
            try:
                await self._session.close()
            except Exception:
                pass
        self._session = self._session_factory()
        return self._session
    
    async def execute(self, statement, *args, **kwargs):
        """Execute a statement with automatic retry on connection errors."""
        last_error = None
        
        for attempt in range(self._max_retries + 1):
            try:
                return await self._session.execute(statement, *args, **kwargs)
            except Exception as e:
                last_error = e
                if is_connection_error(e) and attempt < self._max_retries:
                    delay = 0.5 * (2 ** attempt)
                    logger.warning(
                        f"DB connection error on execute (attempt {attempt + 1}), "
                        f"getting fresh session in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
                    await self._get_fresh_session()
                else:
                    raise
        
        raise last_error
    
    async def get(self, entity, ident, *args, **kwargs):
        """Get an entity by ID with automatic retry on connection errors."""
        last_error = None
        
        for attempt in range(self._max_retries + 1):
            try:
                return await self._session.get(entity, ident, *args, **kwargs)
            except Exception as e:
                last_error = e
                if is_connection_error(e) and attempt < self._max_retries:
                    delay = 0.5 * (2 ** attempt)
                    logger.warning(
                        f"DB connection error on get (attempt {attempt + 1}), "
                        f"getting fresh session in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
                    await self._get_fresh_session()
                else:
                    raise
        
        raise last_error
    
    async def commit(self):
        """Commit with retry."""
        last_error = None
        
        for attempt in range(self._max_retries + 1):
            try:
                return await self._session.commit()
            except Exception as e:
                last_error = e
                if is_connection_error(e) and attempt < self._max_retries:
                    delay = 0.5 * (2 ** attempt)
                    logger.warning(
                        f"DB connection error on commit (attempt {attempt + 1}), "
                        f"getting fresh session in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
                    await self._get_fresh_session()
                else:
                    raise
        
        raise last_error
    
    async def rollback(self):
        """Rollback."""
        try:
            return await self._session.rollback()
        except Exception:
            pass  # Ignore rollback errors
    
    async def refresh(self, instance, *args, **kwargs):
        """Refresh an instance."""
        return await self._session.refresh(instance, *args, **kwargs)
    
    def add(self, instance):
        """Add an instance."""
        return self._session.add(instance)
    
    async def delete(self, instance):
        """Delete an instance."""
        return await self._session.delete(instance)
    
    async def scalar(self, statement, *args, **kwargs):
        """Execute and return scalar with retry."""
        result = await self.execute(statement, *args, **kwargs)
        return result.scalar()
    
    @property
    def session(self) -> AsyncSession:
        """Get the underlying session for advanced operations."""
        return self._session


async def get_db_session_with_retry() -> AsyncGenerator[RetryableSession, None]:
    """
    Dependency that provides a retryable database session.
    
    Use this for endpoints that make multiple sequential queries where
    connection stability is a concern (e.g., status endpoints with many counts).
    
    Usage:
        @router.get("/")
        async def endpoint(db: RetryableSession = Depends(get_db_session_with_retry)):
            ...
    """
    async with RetryableSession(SessionLocal) as session:
        yield session
