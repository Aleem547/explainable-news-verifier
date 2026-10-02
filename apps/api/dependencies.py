from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis

from apps.api.core.config import get_settings

settings = get_settings()


def get_redis_client() -> Redis:
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
    )


def get_qdrant_client() -> AsyncQdrantClient:
    return AsyncQdrantClient(
        url=settings.qdrant_url,
    )
