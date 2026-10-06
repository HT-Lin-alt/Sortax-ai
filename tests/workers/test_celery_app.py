from sortax.workers.celery_app import celery_app, ping


def test_worker_uses_json_and_utc() -> None:
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.enable_utc is True
    assert celery_app.conf.timezone == "UTC"


def test_worker_ping_task_is_local_and_deterministic() -> None:
    assert ping.run() == "pong"
