import os
import click
from flask.cli import with_appcontext
from redis import Redis
from rq import Worker, Queue

@click.command("worker")
@with_appcontext
def worker_command():
    """Lance un worker RQ pour traiter les paiements."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost")
    redis_conn = Redis.from_url(redis_url)

    print("🚀 Worker RQ démarré... en attente de jobs dans la file par défaut")
    q = Queue(connection=redis_conn)
    worker = Worker([q], connection=redis_conn)
    worker.work()
