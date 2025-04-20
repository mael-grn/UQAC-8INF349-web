# redis_client.py
import os
import redis

# Connexion au Redis distant ou local
redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(redis_url)
