"""Opt-in packaged-runtime smoke test; never connects to physical cameras."""

from datetime import datetime, timedelta
import csv
import json
import os
from pathlib import Path
import time
import traceback


def run_self_test(report_path: str) -> int:
    report = Path(report_path).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    result = {"ok": False, "checks": [], "hardware_connected": False}
    camera = processor = storage = tab = server = None
    try:
        import numpy as np
        from PIL import Image
        from PySide6.QtWidgets import QApplication
        from .background_io import BackgroundFileIO
        from .camera_process import ProcessCameraController
        from .processing_process import ProcessDataProcessor
        from .resources import app_icon_path, user_settings_path
        from .settings_store import load_user_settings
        from .ui.concentration_tab import ConcentrationTab
        from .remote_server import RemoteControlServer

        app = QApplication.instance() or QApplication([])
        assert app_icon_path() is not None, "Application icon missing"
        assert user_settings_path().is_file(), "External portable configuration missing"
        settings, gases = load_user_settings()
        assert settings and gases, "Portable configuration did not load"
        result["checks"].append("configuration_and_icon")

        # Load the actual SDK DLL and exercise frozen multiprocessing without
        # initializing/enumerating hardware or taking ownership of a camera.
        camera = ProcessCameraController()
        sdk_pid = camera.ping()
        assert sdk_pid != os.getpid()
        camera.uninitialize()
        result["checks"].append("sdk_dll_and_camera_process")

        frame = np.arange(8 * 128, dtype=np.uint16).reshape(8, 128)
        processor = ProcessDataProcessor(timeout_seconds=30)
        processor.submit(frame, {"row_groups_text": "1-4 5-8", "arpls_enabled": True},
                         gases, generation=1, batch_mode=True)
        deadline = time.monotonic() + 40
        outcome = None
        while time.monotonic() < deadline and outcome is None:
            outcome = processor.poll()
            app.processEvents()
            time.sleep(0.01)
        assert outcome is not None and outcome.ok, str(outcome)
        payload = outcome.payload
        assert payload["result"].shape == (2, 128)
        assert payload["worker_pid"] != os.getpid()
        processor.shutdown()
        result["checks"].append("processing_process_arpls")

        tab = ConcentrationTab()
        tab.resize(1200, 760)
        now = datetime.now().astimezone()
        for offset in range(3):
            tab.add_data_point(payload["all_results"], payload["labels"],
                               group_ids=payload["group_ids"],
                               measurement_time=now + timedelta(seconds=offset))
        tab.show()
        app.processEvents()
        assert tab.grab().save(str(report.with_suffix(".png")))
        result["checks"].append("qt_concentration_page")

        from .row_group_io import detect_profile_groups, read_groups_csv, write_groups_csv
        from .ui.row_group_dialog import RowGroupDialog
        from .ui.data_tab import DataTab
        x = np.arange(300)
        profile = 1 + 50 * np.exp(-0.5 * ((x - 60) / 8) ** 2)
        profile += 40 * np.exp(-0.5 * ((x - 200) / 8) ** 2)
        probes = detect_profile_groups(profile)
        assert len(probes) == 2
        probe_csv = report.with_name("probe-roundtrip.csv")
        write_groups_csv(probe_csv, probes)
        assert read_groups_csv(probe_csv) == probes
        dialog = RowGroupDialog([], {})
        spectrum = DataTab()
        try:
            dialog._replace_rows(probes)
            assert len(dialog.values()[0]) == 2
            spectrum.display_array(np.ones((1, 100)))
            spectrum._cursor_toggle_cb.setChecked(True)
            spectrum._cursor_on = True
            spectrum._cursor_idx = 50
            spectrum.display_array(np.full((1, 100), 2.0))
            assert spectrum._cursor_on and spectrum._cursor_idx == 50
        finally:
            dialog.close()
            spectrum.close()
        result["checks"].append("probe_detection_csv_and_cursor")

        storage = BackgroundFileIO(timeout_seconds=30)
        def wait_file():
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                for _, status, detail in storage.poll():
                    if status == "error":
                        raise RuntimeError(detail)
                    if status == "done":
                        return
                app.processEvents()
                time.sleep(0.02)
            raise TimeoutError("Frozen file process did not finish")

        image_path = report.with_suffix(".tif")
        storage.submit("image", image_path, frame)
        wait_file()
        with Image.open(image_path) as image:
            np.testing.assert_array_equal(np.asarray(image), frame)
        csv_path = report.with_suffix(".csv")
        storage.submit("csv", csv_path, {
            "columns": [("Test", [10, 20], [now, now + timedelta(seconds=3)])],
            "sample_rate": 1000,
        })
        wait_file()
        with csv_path.open(encoding="utf-8-sig", newline="") as stream:
            assert sum(1 for _ in csv.reader(stream)) == 3002
        storage.close()
        result["checks"].append("file_process_tiff_and_1000hz_csv")

        from urllib.request import urlopen
        server = RemoteControlServer()
        assert server.start("127.0.0.1", 0, "", "packaging-self-test")
        for resource in ("/", "/remote_dashboard.js", "/remote_dashboard.css"):
            with urlopen(f"http://127.0.0.1:{server.port}{resource}", timeout=5) as response:
                body = response.read()
                assert response.status == 200 and body
                if resource == "/":
                    assert b'id="exposure"' not in body
        server.stop()
        result["checks"].append("remote_web_resources")

        from unittest.mock import patch
        from .ui.main_window import MainWindow
        offline_settings = dict(settings, remote_enabled=False, plot_opengl_enabled=False)
        with patch.object(MainWindow, "_try_connect", lambda self: None), \
                patch("tucam_control.ui.main_window.load_user_settings", return_value=(offline_settings, gases)), \
                patch("tucam_control.ui.main_window.save_user_settings"):
            window = MainWindow()
            try:
                window.show()
                app.processEvents()
                assert window.isVisible()
                assert window.grab().save(str(report.with_name("main-window.png")))
                result["checks"].append("main_window_offline_startup")
            finally:
                window.close()
                window.deleteLater()
                app.processEvents()
        result["ok"] = True
    except Exception:
        result["error"] = traceback.format_exc()
    finally:
        for item, action in ((server, "stop"), (storage, "cancel"),
                             (processor, "shutdown"), (camera, "uninitialize"), (tab, "close")):
            if item is not None:
                try:
                    getattr(item, action)()
                except Exception:
                    result["ok"] = False
                    result.setdefault("cleanup_errors", []).append(traceback.format_exc())
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1
