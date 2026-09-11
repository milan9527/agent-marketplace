"""Poll the durable workflow queue independently of web requests."""

import logging
import signal
import threading
from uuid import uuid4

from app.agents import invoke_runtime
from app.config import get_settings
from app.automation import advance_automation, has_ready_job
from app.db import session_factory


def main():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("workflow-worker")
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    settings = get_settings()
    runtime_session = str(uuid4())
    while not stop.is_set():
        try:
            # Poll RDS locally. An empty queue must not create billable Runtime
            # sessions. One worker reuses its orchestration session for work.
            with session_factory()() as db:
                ready = has_ready_job(db)
            if not ready:
                stop.wait(3)
                continue
            if settings.app_mode == "aws":
                result = invoke_runtime(
                    settings.orchestrator_runtime_arn,
                    {"action": "advance_automation"},
                    session_id=runtime_session,
                )
            else:
                with session_factory()() as db:
                    result = advance_automation(db)
            if result.get("processed"):
                logger.info(
                    "Task %s: workflow=%s stage=%s",
                    result["task_id"],
                    result["status"],
                    result["stage"],
                )
                continue
        except Exception as exc:
            # Persisted leases and task/payment state handle interrupted calls.
            # Never log credentials, provider payloads, or payment proofs.
            logger.warning("Workflow poll failed (%s)", type(exc).__name__)
            runtime_session = str(uuid4())
        stop.wait(3)


if __name__ == "__main__":
    main()
