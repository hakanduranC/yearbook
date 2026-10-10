"""Background thread that keeps a claimed job's `locked_at` fresh while it runs."""

from __future__ import annotations

import threading
from types import TracebackType

from psycopg_pool import ConnectionPool

from yearbook_worker import queue
from yearbook_worker.log import get_logger

log = get_logger(__name__)


class Heartbeat:
    """Refresh the lock every `interval` seconds; records when the lock was lost."""

    def __init__(
        self, pool: ConnectionPool, job_id: int, locked_by: str, interval: float = 30.0
    ) -> None:
        self.pool = pool
        self.job_id = job_id
        self.locked_by = locked_by
        self.interval = interval
        self.lost = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"heartbeat-{job_id}", daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                with self.pool.connection() as conn:
                    ok = queue.heartbeat(conn, self.job_id, self.locked_by)
            except Exception as exc:
                log.warning("heartbeat.error", job_id=self.job_id, error=str(exc))
                continue
            if not ok:
                self.lost = True
                log.warning("heartbeat.lock_lost", job_id=self.job_id)

    def __enter__(self) -> Heartbeat:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
