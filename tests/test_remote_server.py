# -*- coding: utf-8 -*-

from __future__ import annotations

from http.client import HTTPResponse
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tucam_control.remote_server import RemoteControlServer


def _request(
    base_url: str,
    path: str,
    *,
    token: str | None = None,
    method: str = "GET",
) -> tuple[int, bytes]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = Request(base_url + path, headers=headers, method=method)
    try:
        response: HTTPResponse = urlopen(request, timeout=2.0)
        return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def test_remote_server_auth_snapshot_and_command_queue() -> None:
    server = RemoteControlServer()
    assert server.start("127.0.0.1", 0, "", "test-key") is True
    base_url = f"http://127.0.0.1:{server.port}"
    try:
        status, body = _request(base_url, "/")
        assert status == 200
        assert "Dhyana 95 V2 远程控制" in body.decode("utf-8")

        status, body = _request(base_url, "/remote_dashboard.js")
        assert status == 200
        assert b"requestAnimationFrame" in body
        status, body = _request(base_url, "/remote_dashboard.css")
        assert status == 200
        assert b".status-grid" in body

        status, _ = _request(base_url, "/api/status")
        assert status == 401

        server.update_snapshot(connected=True, status="ready")
        status, body = _request(base_url, "/api/status", token="test-key")
        payload = json.loads(body)
        assert status == 200
        assert payload["connected"] is True
        assert payload["status"] == "ready"

        status, body = _request(
            base_url,
            "/api/commands/start",
            token="test-key",
            method="POST",
        )
        assert status == 202
        assert json.loads(body)["accepted"] is True
        command_id = json.loads(body)["command"]["command_id"]
        status, body = _request(
            base_url,
            f"/api/commands/{command_id}",
            token="test-key",
        )
        assert status == 200
        assert json.loads(body)["state"] == "pending"
        command = server.poll_command()
        assert command is not None
        assert command.action == "start"
        assert command.client_ip == "127.0.0.1"

        server.record_command_result(command, True, "started")
        assert server.snapshot()["last_command"]["message"] == "started"
        status, body = _request(
            base_url,
            f"/api/commands/{command_id}",
            token="test-key",
        )
        assert status == 200
        result = json.loads(body)
        assert result["state"] == "completed"
        assert result["ok"] is True
    finally:
        server.stop()


def test_remote_server_rejects_disallowed_client_ip() -> None:
    server = RemoteControlServer()
    assert server.start("127.0.0.1", 0, "192.0.2.10", "test-key") is True
    base_url = f"http://127.0.0.1:{server.port}"
    try:
        status, _ = _request(base_url, "/api/status", token="test-key")
        assert status == 403
        status, _ = _request(
            base_url,
            "/api/commands/stop",
            token="test-key",
            method="POST",
        )
        assert status == 403
        assert server.poll_command() is None
    finally:
        server.stop()


def test_stopping_remote_server_discards_pending_commands() -> None:
    server = RemoteControlServer()
    command = server.enqueue_command("start", "127.0.0.1")
    assert command is not None

    server.stop()

    assert server.poll_command() is None


def test_remote_updates_return_every_measurement_and_gap() -> None:
    server = RemoteControlServer()
    concentrations = [{
        "probe_id": "probe-1",
        "probe": "探头 A",
        "gas": "halon",
        "concentration_percent": 2.0,
        "detected": True,
    }]
    server.append_measurement(1, 1000, "2026-08-20T10:00:01+08:00", concentrations)
    concentrations[0]["concentration_percent"] = 2.5
    server.append_measurement(2, 1400, "2026-08-20T10:00:01.400+08:00", concentrations)
    server.append_gap(3, 1500, "capture-stop")
    concentrations[0]["concentration_percent"] = 3.0
    server.append_measurement(4, 2000, "2026-08-20T10:00:02+08:00", concentrations)

    first = server.updates(after_id=0, limit=2)
    assert [item["id"] for item in first["measurements"]] == [1, 2]
    assert first["has_more"] is True
    assert first["measurements"][0]["concentrations"][0]["concentration_percent"] == 2.0

    second = server.updates(after_id=2)
    assert [(item["id"], item["kind"]) for item in second["measurements"]] == [
        (3, "gap"),
        (4, "measurement"),
    ]
    assert second["has_more"] is False


def test_reset_measurements_changes_stream_epoch() -> None:
    server = RemoteControlServer()
    server.append_measurement(7, 1000, "time", [])
    before = server.updates()["stream_epoch"]

    server.reset_measurements()

    updates = server.updates()
    assert updates["stream_epoch"] != before
    assert updates["measurements"] == []
    assert updates["status"]["measurement_id"] == 0
