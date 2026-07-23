from __future__ import annotations

from types import SimpleNamespace

from tucam_control.ui.main_window import MainWindow


class _SignalRecorder:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def emit(self, message: str) -> None:
        self.messages.append(message)


def test_manual_emergency_stop_is_preserved() -> None:
    stopped: list[str] = []
    capture_states: list[bool] = []
    batch_states: list[bool] = []
    window = SimpleNamespace(
        _batch_timer=SimpleNamespace(stop=lambda: None),
        _stop_continuous_capture=stopped.append,
        _acq_tab=SimpleNamespace(
            set_capturing_state=capture_states.append,
            set_batch_state=batch_states.append,
        ),
        status_changed=_SignalRecorder(),
    )

    MainWindow._on_emergency_stop(window)

    assert stopped == ["manual emergency stop"]
    assert capture_states == [False]
    assert batch_states == [False]


def test_legacy_automatic_alarm_handler_is_removed() -> None:
    assert not hasattr(MainWindow, "_check_smoothed_gas_alarm")
