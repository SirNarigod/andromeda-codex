from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any


class TickBackgroundService:
    """Opt-in daemon scheduler: one serialized tick at a time per world."""

    def __init__(self, orchestrator: Any, *, interval_s: float = 0.05) -> None:
        if interval_s <= 0:
            raise ValueError("interval_s must be positive")
        self.orchestrator = orchestrator
        self.interval_s = float(interval_s)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._world_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._worlds: set[str] = set()
        self._errors: list[dict[str, str]] = []
        self._ticks = 0

    @property
    def thread(self) -> threading.Thread | None:
        return self._thread

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def ticks_completed(self) -> int:
        with self._lock:
            return self._ticks

    @property
    def errors(self) -> list[dict[str, str]]:
        with self._lock:
            return list(self._errors)

    def register_world(self, world_instance_id: str) -> None:
        with self._lock:
            self._worlds.add(world_instance_id)
        self._wake.set()

    def unregister_world(self, world_instance_id: str) -> None:
        with self._lock:
            self._worlds.discard(world_instance_id)

    def start(self) -> None:
        with self._lock:
            if self.is_running:
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="andromeda-world-tick",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        thread = self._thread
        if thread is None:
            return
        self._stop.set()
        self._wake.set()
        if thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout_s))
        if thread.is_alive():
            raise RuntimeError("tick background thread did not stop cleanly")
        with self._lock:
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(self.interval_s)
            self._wake.clear()
            with self._lock:
                worlds = tuple(self._worlds)
            for world_id in worlds:
                if self._stop.is_set():
                    break
                gate = self._world_locks[world_id]
                if not gate.acquire(blocking=False):
                    continue
                try:
                    self.orchestrator.run_tick(world_id)
                    with self._lock:
                        self._ticks += 1
                except Exception as exc:
                    with self._lock:
                        self._errors.append({"world_instance_id": world_id, "error": repr(exc)})
                finally:
                    gate.release()

    def __enter__(self) -> "TickBackgroundService":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop()