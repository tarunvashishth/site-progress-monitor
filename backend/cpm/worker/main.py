import logging
import signal
import time

from cpm.core.config import get_settings
from cpm.core.db import one, service_tx
from cpm.core.storage import Storage
from cpm.pipeline.errors import PermanentError
from cpm.worker.jobs import run_job

log = logging.getLogger("cpm.worker")
_running = True


def _stop(*_: object) -> None:
    global _running
    _running = False


def claim() -> dict | None:
    with service_tx() as c:
        return one(c, "select * from public.claim_next_job()")


def _finish(job: dict, error: str | None, permanent: bool) -> None:
    with service_tx() as c:
        if error is None:
            c.execute(
                "update public.video_processing_jobs set status='succeeded', completed_at=now(), "
                "error_message=null where id=%s",
                (job["id"],),
            )
        elif permanent or job["attempts"] >= job["max_attempts"]:
            c.execute(
                "update public.video_processing_jobs set status='failed', completed_at=now(), "
                "error_message=%s where id=%s",
                (error, job["id"]),
            )
            c.execute(
                "update public.drone_videos set status='failed', processing_error=%s where id=%s",
                (error, job["video_id"]),
            )
            c.execute(
                "update public.ai_analyses set status='failed', error_message=%s, completed_at=now() "
                "where job_id=%s and status='running'",
                (error, job["id"]),
            )
        else:  # transient: back to the queue
            c.execute(
                "update public.video_processing_jobs set status='queued', locked_at=null, "
                "error_message=%s where id=%s",
                (error, job["id"]),
            )
            c.execute(
                "update public.drone_videos set status='queued' where id=%s", (job["video_id"],)
            )


def run_once(storage: Storage | None = None, provider=None) -> bool:
    job = claim()
    if not job:
        return False
    s = get_settings()
    log.info("job %s (%s) attempt %s", job["id"], job["job_type"], job["attempts"])
    try:
        run_job(job, storage or Storage(s), s, provider)
        _finish(job, None, False)
    except PermanentError as e:
        log.warning("job %s failed permanently: %s", job["id"], e)
        _finish(job, str(e), True)
    except Exception as e:  # noqa: BLE001 - transient or unexpected; message is user-safe, details are logged
        log.exception("job %s errored", job["id"])
        _finish(
            job,
            str(e) if type(e).__name__ == "TransientError" else "Unexpected processing error",
            False,
        )
    return True


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    s = get_settings()
    log.info("worker started (poll %ss, AI configured: %s)", s.poll_interval_sec, s.ai_configured)
    while _running:
        try:
            if run_once():
                continue
        except Exception:  # noqa: BLE001
            log.exception("worker loop error")
        time.sleep(s.poll_interval_sec)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
