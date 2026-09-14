import redis.asyncio as redis

from app.config import get_settings


def get_redis() -> redis.Redis:
    settings = get_settings()
    return redis.from_url(settings.redis_url, decode_responses=True)
