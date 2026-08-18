from redis import Redis
from rq import Queue

from .config import settings

redis_conn = Redis.from_url(settings.redis_url)
task_queue = Queue("tasks", connection=redis_conn)
