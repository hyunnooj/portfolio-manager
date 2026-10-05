import os
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from celery import Celery
from celery.contrib.testing.worker import start_worker

from app.jobs.celery_app import health_task


@pytest.mark.queue
def test_real_redis_worker_delivery():
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("Set TEST_REDIS_URL to a dedicated Redis test DB (e.g. /15)")
    if urlsplit(url).path in {"", "/", "/0"}:
        pytest.fail("TEST_REDIS_URL must use a dedicated nonzero Redis DB")
    queue = "test_" + uuid4().hex
    test_app = Celery("foundation_test", broker=url, backend=url)
    test_app.conf.update(
        task_serializer="json", result_serializer="json", accept_content=["json"], result_expires=60
    )
    task = test_app.task(name="foundation.health")(health_task.run)
    with test_app.connection_for_write() as connection:
        connection.ensure_connection(max_retries=0)
    try:
        with start_worker(
            test_app, pool="solo", queues=[queue], perform_ping_check=False, shutdown_timeout=15
        ):
            result = task.apply_async(queue=queue)
            assert result.get(timeout=15) == {"status": "OK"}
            result.forget()
    finally:
        test_app.close()
