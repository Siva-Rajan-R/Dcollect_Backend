from redis import asyncio as aioredis
from app.core.config import settings

class RedisClient:
    redis: aioredis.Redis = None

redis_client = RedisClient()

async def connect_to_redis():
    redis_client.redis = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    print("Connected to Redis")

async def close_redis_connection():
    if redis_client.redis:
        await redis_client.redis.close()
        print("Closed Redis connection")
