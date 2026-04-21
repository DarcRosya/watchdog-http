import redis.asyncio as aioredis


def create_redis_client(host: str, port: int) -> aioredis.Redis:
    """Create a Redis client connected to the given host/port.

    The returned client uses an internal connection pool and is safe to share
    for the lifetime of the process (API server or Telegram bot).
    """
    return aioredis.Redis.from_url(
        f"redis://{host}:{port}",
        encoding="utf-8",
        decode_responses=True,
    )
