from fastapi import APIRouter
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis
from sqlalchemy import text

from apps.api.core.config import get_settings
from apps.api.db.session import AsyncSessionLocal
from apps.api.dependencies import get_qdrant_client, get_redis_client

router = APIRouter(tags=["health"])

settings = get_settings()


@router.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@router.get("/ready")
async def readiness() -> dict[str, object]:
    checks: dict[str, str] = {}

    # PostgreSQL
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "error"

    # Redis
    redis_client: Redis = get_redis_client()

    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"
    finally:
        await redis_client.aclose()

    # Qdrant
    qdrant_client: AsyncQdrantClient = get_qdrant_client()

    try:
        await qdrant_client.get_collections()
        checks["qdrant"] = "ok"
    except Exception:
        checks["qdrant"] = "error"
    finally:
        await qdrant_client.close()

    ready = all(value == "ok" for value in checks.values())

    return {
        "ready": ready,
        "checks": checks,
    }
