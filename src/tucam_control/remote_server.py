# -*- coding: utf-8 -*-
"""Offline LAN HTTP server for remote monitoring and acquisition control."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
from queue import Empty, Full, Queue
import secrets
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit


log = logging.getLogger("tucam_control.remote_server")

REMOTE_HISTORY_RETENTION_SECONDS = 120.0
REMOTE_HISTORY_MAX_FRAMES = 5000
REMOTE_UPDATES_MAX_LIMIT = 1000


def generate_remote_token() -> str:
    return secrets.token_urlsafe(18)


def local_ipv4_addresses() -> list[str]:
    """Return non-loopback IPv4 addresses suitable for LAN access hints."""
    addresses: set[str] = set()
    try:
        for item in socket.getaddrinfo(
            socket.gethostname(),
            None,
            family=socket.AF_INET,
        ):
            address = str(item[4][0])
            if address and not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)


@dataclass(frozen=True)
class RemoteCommand:
    command_id: str
    action: str
    client_ip: str
    requested_at: float


class _RemoteHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class RemoteControlServer:
    """Threaded local HTTP server; camera commands are queued for Qt."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._commands: Queue[RemoteCommand] = Queue(maxsize=64)
        self._command_results: dict[str, dict] = {}
        self._measurements: deque[dict] = deque(maxlen=REMOTE_HISTORY_MAX_FRAMES)
        self._stream_epoch = secrets.token_hex(8)
        self._snapshot: dict = {
            "service": "Dhyana-95-V2 Remote Control",
            "updated_at": None,
            "connected": False,
            "capturing": False,
            "batch_running": False,
            "status": "软件正在启动 / Starting",
            "camera": {},
            "diagnostics": {},
            "measurement_id": 0,
            "measurement_time": None,
            "concentrations": [],
            "last_command": None,
        }
        self._server: _RemoteHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._configuration: tuple[str, int, str, str] | None = None
        self._last_error = ""

    @property
    def is_running(self) -> bool:
        return self._server is not None and self._thread is not None and self._thread.is_alive()

    @property
    def port(self) -> int | None:
        return int(self._server.server_address[1]) if self._server is not None else None

    @property
    def last_error(self) -> str:
        return self._last_error

    def start(
        self,
        host: str,
        port: int,
        allowed_ip: str,
        token: str,
    ) -> bool:
        normalized = (
            str(host).strip() or "0.0.0.0",
            int(port),
            str(allowed_ip).strip(),
            str(token).strip(),
        )
        if self.is_running and normalized == self._configuration:
            return True
        self.stop()
        if not normalized[3]:
            self._last_error = "远程访问密钥不能为空"
            return False

        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "TUCamRemote/1.0"

            def log_message(self, format_string: str, *args) -> None:
                log.debug("remote_http client=%s " + format_string, self.client_address[0], *args)

            def _client_allowed(self) -> bool:
                expected = normalized[2]
                return not expected or self.client_address[0] == expected

            def _authorized(self) -> bool:
                supplied = self.headers.get("Authorization", "")
                expected = f"Bearer {normalized[3]}"
                return secrets.compare_digest(supplied, expected)

            def _send_bytes(
                self,
                status: HTTPStatus,
                body: bytes,
                content_type: str,
            ) -> None:
                self.send_response(int(status))
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.end_headers()
                self.wfile.write(body)

            def _send_json(self, status: HTTPStatus, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self._send_bytes(status, body, "application/json; charset=utf-8")

            def _reject_if_needed(self) -> bool:
                if not self._client_allowed():
                    self._send_json(HTTPStatus.FORBIDDEN, {"error": "client IP not allowed"})
                    return True
                if not self._authorized():
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid access key"})
                    return True
                return False

            def do_GET(self) -> None:  # noqa: N802
                request_url = urlsplit(self.path)
                path = request_url.path
                if path == "/":
                    body = owner._dashboard_html()
                    self._send_bytes(HTTPStatus.OK, body, "text/html; charset=utf-8")
                    return
                dashboard_assets = {
                    "/remote_dashboard.css": ("remote_dashboard.css", "text/css; charset=utf-8"),
                    "/remote_dashboard.js": ("remote_dashboard.js", "text/javascript; charset=utf-8"),
                }
                if path in dashboard_assets:
                    filename, content_type = dashboard_assets[path]
                    self._send_bytes(
                        HTTPStatus.OK,
                        owner._dashboard_asset(filename),
                        content_type,
                    )
                    return
                if path == "/api/health":
                    self._send_json(HTTPStatus.OK, {"ok": True})
                    return
                if path == "/api/status":
                    if self._reject_if_needed():
                        return
                    self._send_json(HTTPStatus.OK, owner.snapshot())
                    return
                if path == "/api/updates":
                    if self._reject_if_needed():
                        return
                    query = parse_qs(request_url.query)
                    try:
                        after_id = int(query.get("after", ["0"])[0])
                        limit = int(query.get("limit", ["500"])[0])
                    except (TypeError, ValueError):
                        self._send_json(
                            HTTPStatus.BAD_REQUEST,
                            {"error": "invalid update cursor"},
                        )
                        return
                    self._send_json(
                        HTTPStatus.OK,
                        owner.updates(after_id=after_id, limit=limit),
                    )
                    return
                command_status_prefix = "/api/commands/"
                if path.startswith(command_status_prefix):
                    if self._reject_if_needed():
                        return
                    command_id = path[len(command_status_prefix):]
                    command_status = owner.command_status(command_id)
                    if command_status is None:
                        self._send_json(
                            HTTPStatus.NOT_FOUND,
                            {"error": "command not found"},
                        )
                    else:
                        self._send_json(HTTPStatus.OK, command_status)
                    return
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                if self._reject_if_needed():
                    return
                path = self.path.split("?", 1)[0]
                prefix = "/api/commands/"
                if not path.startswith(prefix):
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
                action = path[len(prefix):]
                if action not in {"start", "stop", "emergency-stop"}:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "unknown command"})
                    return
                command = owner.enqueue_command(action, self.client_address[0])
                if command is None:
                    self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "command queue full"})
                    return
                self._send_json(
                    HTTPStatus.ACCEPTED,
                    {"accepted": True, "command": asdict(command)},
                )

        try:
            server = _RemoteHTTPServer((normalized[0], normalized[1]), Handler)
        except OSError as exc:
            self._last_error = str(exc)
            log.exception("Remote server could not bind to %s:%s", normalized[0], normalized[1])
            return False

        self._server = server
        self._configuration = normalized
        self._last_error = ""
        self._thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.2},
            name="TUCamRemoteHTTP",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "Remote server started host=%s port=%s allowed_ip=%s",
            normalized[0],
            self.port,
            normalized[2] or "any",
        )
        return True

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        self._configuration = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        while True:
            try:
                self._commands.get_nowait()
            except Empty:
                break
        if server is not None:
            log.info("Remote server stopped")

    def update_snapshot(self, **values) -> None:
        with self._lock:
            self._snapshot.update(deepcopy(values))
            self._snapshot["updated_at"] = time.time()

    def snapshot(self) -> dict:
        with self._lock:
            return deepcopy(self._snapshot)

    def append_measurement(
        self,
        measurement_id: int,
        timestamp_ms: int,
        measurement_time: str,
        concentrations: list[dict],
    ) -> None:
        frame = {
            "kind": "measurement",
            "id": int(measurement_id),
            "timestamp_ms": int(timestamp_ms),
            "measurement_time": str(measurement_time),
            "concentrations": deepcopy(concentrations),
        }
        with self._lock:
            self._measurements.append(frame)
            self._prune_measurements_locked(frame["timestamp_ms"])
            self._snapshot.update({
                "measurement_id": frame["id"],
                "measurement_time": frame["measurement_time"],
                "concentrations": deepcopy(frame["concentrations"]),
                "updated_at": time.time(),
            })

    def append_gap(
        self,
        measurement_id: int,
        timestamp_ms: int,
        reason: str,
    ) -> None:
        frame = {
            "kind": "gap",
            "id": int(measurement_id),
            "timestamp_ms": int(timestamp_ms),
            "reason": str(reason),
        }
        with self._lock:
            self._measurements.append(frame)
            self._prune_measurements_locked(frame["timestamp_ms"])

    def reset_measurements(self) -> None:
        with self._lock:
            self._measurements.clear()
            self._stream_epoch = secrets.token_hex(8)
            self._snapshot.update({
                "measurement_id": 0,
                "measurement_time": None,
                "concentrations": [],
                "updated_at": time.time(),
            })

    def updates(self, after_id: int = 0, limit: int = 500) -> dict:
        normalized_after = max(0, int(after_id))
        normalized_limit = max(1, min(REMOTE_UPDATES_MAX_LIMIT, int(limit)))
        with self._lock:
            measurements = list(self._measurements)
            oldest_id = int(measurements[0]["id"]) if measurements else 0
            latest_id = int(measurements[-1]["id"]) if measurements else 0
            reset_required = bool(
                measurements
                and normalized_after > 0
                and normalized_after < oldest_id - 1
            )
            if reset_required:
                selected = measurements[:normalized_limit]
            else:
                selected = [
                    frame for frame in measurements
                    if int(frame["id"]) > normalized_after
                ][:normalized_limit]
            snapshot = deepcopy(self._snapshot)
            stream_epoch = self._stream_epoch
        return {
            "server_time_ms": int(time.time() * 1000.0),
            "stream_epoch": stream_epoch,
            "oldest_id": oldest_id,
            "latest_id": latest_id,
            "reset_required": reset_required,
            "has_more": bool(selected and int(selected[-1]["id"]) < latest_id),
            "measurements": deepcopy(selected),
            "status": snapshot,
        }

    def _prune_measurements_locked(self, latest_timestamp_ms: int) -> None:
        cutoff_ms = int(
            latest_timestamp_ms - REMOTE_HISTORY_RETENTION_SECONDS * 1000.0
        )
        while (
            self._measurements
            and int(self._measurements[0]["timestamp_ms"]) < cutoff_ms
        ):
            self._measurements.popleft()

    def enqueue_command(self, action: str, client_ip: str) -> RemoteCommand | None:
        command = RemoteCommand(
            command_id=secrets.token_hex(8),
            action=str(action),
            client_ip=str(client_ip),
            requested_at=time.time(),
        )
        try:
            self._commands.put_nowait(command)
        except Full:
            return None
        with self._lock:
            self._command_results[command.command_id] = {
                "id": command.command_id,
                "action": command.action,
                "client_ip": command.client_ip,
                "requested_at": command.requested_at,
                "state": "pending",
            }
            self._trim_command_results_locked()
        log.info(
            "Remote command queued id=%s action=%s client=%s",
            command.command_id,
            command.action,
            command.client_ip,
        )
        return command

    def poll_command(self) -> RemoteCommand | None:
        try:
            return self._commands.get_nowait()
        except Empty:
            return None

    def record_command_result(self, command: RemoteCommand, ok: bool, message: str) -> None:
        result = {
            "id": command.command_id,
            "action": command.action,
            "client_ip": command.client_ip,
            "requested_at": command.requested_at,
            "completed_at": time.time(),
            "ok": bool(ok),
            "message": str(message),
            "state": "completed",
        }
        with self._lock:
            self._command_results[command.command_id] = deepcopy(result)
            self._trim_command_results_locked()
        self.update_snapshot(last_command=result)
        log.info(
            "Remote command completed id=%s action=%s ok=%s message=%s",
            command.command_id,
            command.action,
            ok,
            message,
        )

    def command_status(self, command_id: str) -> dict | None:
        with self._lock:
            result = self._command_results.get(str(command_id))
            return deepcopy(result) if result is not None else None

    def _trim_command_results_locked(self) -> None:
        while len(self._command_results) > 128:
            oldest = next(iter(self._command_results))
            del self._command_results[oldest]

    @staticmethod
    def _dashboard_html() -> bytes:
        return RemoteControlServer._dashboard_asset("remote_dashboard.html")

    @staticmethod
    def _dashboard_asset(filename: str) -> bytes:
        return Path(__file__).with_name(filename).read_bytes()
