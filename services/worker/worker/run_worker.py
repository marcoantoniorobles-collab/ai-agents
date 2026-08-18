import logging

from redis import Redis
from rq import Queue, Worker

from .config import settings

logging.basicConfig(level=logging.INFO)


def main() -> None:
    conn = Redis.from_url(settings.redis_url)
    worker = Worker([Queue("tasks", connection=conn)], connection=conn)
    worker.work(with_scheduler=True)  # with_scheduler=True habilita enqueue_in (reintentos con delay)


if __name__ == "__main__":
    main()
