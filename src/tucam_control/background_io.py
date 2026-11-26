"""Isolated file jobs with bounded queues, timeout and atomic publication."""

from __future__ import annotations

from collections import deque
import multiprocessing as mp
from pathlib import Path
import queue
import time
import uuid


def _file_worker(requests, results):
    while True:
        job = requests.get()
        if job is None:
            return
        job_id, kind, path, temporary, payload = job
        try:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if kind == "image":
                from PIL import Image
                Image.fromarray(payload).save(temporary, format="TIFF")
            elif kind == "csv":
                from .concentration_export import write_concentration_csv
                write_concentration_csv(
                    temporary, **payload,
                    progress=lambda value: results.put((job_id, "progress", value)),
                )
            else:
                raise ValueError(f"Unknown file operation: {kind}")
            Path(temporary).replace(target)
            results.put((job_id, "done", path))
        except Exception as exc:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass
            results.put((job_id, "error", str(exc)))


class BackgroundFileIO:
    def __init__(self, capacity=8, timeout_seconds=30.0):
        self._ctx = mp.get_context("spawn")
        self._capacity = capacity
        self._timeout = timeout_seconds
        self._pending = deque()
        self._active = None
        self._started = 0.0
        self._process = None
        self._requests = None
        self._results = None

    @property
    def is_busy(self):
        return self._active is not None or bool(self._pending)

    def submit(self, kind, path, payload):
        if len(self._pending) + int(self._active is not None) >= self._capacity:
            raise RuntimeError("File queue is full; storage cannot keep up")
        job_id = uuid.uuid4().hex
        temporary = str(Path(path).with_name(f".{Path(path).name}.{job_id}.tmp"))
        self._pending.append((job_id, kind, str(path), temporary, payload))
        try:
            self._dispatch()
        except Exception:
            self.cancel()
            raise
        return job_id

    def _dispatch(self):
        if self._active is not None or not self._pending:
            return
        if self._process is None:
            self._requests = self._ctx.Queue(maxsize=1)
            self._results = self._ctx.Queue()
            self._process = self._ctx.Process(
                target=_file_worker, args=(self._requests, self._results), daemon=True,
                name="TUCamFileIO",
            )
            self._process.start()
        self._active = self._pending.popleft()
        self._started = time.monotonic()
        self._requests.put_nowait(self._active)

    def poll(self):
        events = []
        if self._active is None:
            return events
        for _ in range(64):
            try:
                event = self._results.get_nowait()
            except queue.Empty:
                break
            if event[0] != self._active[0]:
                continue
            events.append(event)
            if event[1] == "progress":
                self._started = time.monotonic()
            else:
                self._active = None
                if event[1] == "done":
                    try:
                        self._dispatch()
                    except Exception as exc:
                        events.append((event[0], "error", str(exc)))
                        self.cancel()
                break
        if self._active is not None and (
            not self._process.is_alive() or time.monotonic() - self._started > self._timeout
        ):
            events.append((self._active[0], "error", "File worker timed out or exited"))
            self.cancel()
        return events

    def cancel(self):
        process = self._process
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=1.0)
            if process.is_alive():
                process.kill()
                process.join(timeout=1.0)
        for channel in (self._requests, self._results):
            if channel is not None:
                channel.cancel_join_thread()
                channel.close()
        # A stalled filesystem may also block unlink; abandoned .tmp files are
        # deliberately left unpublished instead of doing file I/O on the UI thread.
        self._active = None
        self._pending.clear()
        self._process = self._requests = self._results = None

    def close(self):
        if self.is_busy:
            raise RuntimeError("File jobs are still pending")
        self.cancel()
