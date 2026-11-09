"""
api/warmup.py

Day 8: startup warm-up + readiness state.

Problem (Day 7): the first /rca on a new pod took 17.2 s, later ones ~0.4 s.
The embedding model and ChromaDB were loaded on first USE, so the first
real user paid for it -- and Kubernetes already sent that user traffic,
because the old readiness probe (/health) did not know about it.

Fix: load everything in a background thread at startup and run one real
retrieval. /readyz returns 503 until that has succeeded, so Kubernetes
sends no traffic to the pod until it is actually fast.

No FastAPI / model / ChromaDB imports here: the work is passed in as
functions, so CI can test this with plain pytest.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

logger = logging.getLogger("rca.warmup")

WARMING = "warming"
READY = "ready"
FAILED = "warmup_failed"


class Warmup:
    def __init__(self) -> None:
        self.state = WARMING
        self.detail = ""
        self.seconds: float | None = None
        self._lock = threading.Lock()

    def run(self, steps: list[tuple[str, Callable[[], object]]]) -> None:
        """Run each (name, fn) in order. A step that raises, or returns
        False, marks the pod as failed (readiness stays 503)."""
        start = time.perf_counter()
        for name, fn in steps:
            try:
                ok = fn()
            except Exception as exc:  # noqa: BLE001 -- any failure = not ready
                self._set(FAILED, f"{name}: {exc}")
                logger.error("warm-up failed at step %s: %s", name, exc)
                return
            if ok is False:
                self._set(FAILED, f"{name}: returned False")
                logger.error("warm-up failed at step %s: returned False", name)
                return
        self.seconds = round(time.perf_counter() - start, 2)
        self._set(READY, "")
        logger.info("warm-up done in %.2fs", self.seconds)

    def start_in_background(self, steps: list[tuple[str, Callable[[], object]]]) -> threading.Thread:
        t = threading.Thread(target=self.run, args=(steps,), name="warmup", daemon=True)
        t.start()
        return t

    def _set(self, state: str, detail: str) -> None:
        with self._lock:
            self.state = state
            self.detail = detail

    @property
    def ready(self) -> bool:
        return self.state == READY
